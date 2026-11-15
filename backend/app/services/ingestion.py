"""
【檔案用途】文件入庫：把一份上傳的文件變成「可被檢索的 chunk」。
對應職缺：RAG 應用開發（資料前處理、向量化）、PostgreSQL 交易與資料一致性。

整個流程拆成兩段，因為嵌入很慢（每塊都要呼叫模型），不能讓上傳的 HTTP 請求一直等：
  第一段 register_upload（在請求裡，很快）：檢查格式與重複 → 存檔 → 建立 pending 主檔 → 立刻回應 202
  第二段 process_document（在背景）：切塊 → 逐塊嵌入 → 一次寫入 chunk 並改成 ready；失敗就標 failed

文件狀態機：
  pending ──處理成功──> ready ──新版上線或手動作廢──> deprecated
     │
     └──處理失敗──> failed ──管理員按「重新處理」──> pending

設計重點，面試最常被問：
  1. checksum：用「內容」判斷重複，不是用檔名或版本號。
  2. 狀態機 pending → ready / failed：中途失敗不會留下「半份文件」被檢索到，也不會讓文件憑空消失。
  3. 交易邊界：嵌入全部成功才寫 chunk；新版 ready 與舊版 deprecated 在同一個 commit。

被誰呼叫：routers/documents.py（上傳、重新處理）、main.py（啟動時清理卡住的文件）。
"""

import hashlib  # 計算 SHA-256 雜湊（checksum）
import logging  # 背景工作出錯時寫日誌（背景工作的例外沒有人接，不記就消失了）
from collections.abc import Iterator  # 型別註記：session_scope 是一個會 yield 的產生器
from contextlib import contextmanager  # 把 yield 函式變成可以用 with 的「情境管理器」
from datetime import date  # 型別註記：生效日
from pathlib import Path  # 處理檔案路徑、讀寫檔案

# delete / select / update：SQLAlchemy 2.0 寫 SQL 的三個建構函式（DELETE、SELECT、UPDATE）
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session  # 型別註記：資料庫連線的工作階段（交易單位）

from app.core.chunker import split_articles  # 依「第N條」切塊（模型系列）
from app.core.config import settings  # 讀設定：上傳資料夾、Ollama 位址與模型名稱
from app.core.database import SessionLocal  # 產生新的資料庫 session（背景工作要自己開）
from app.core.llm_service import LLMService  # 呼叫嵌入模型（模型系列）
from app.models.document import Document, DocumentChunk  # 文件主檔與切塊兩張表

# 模組自己的 logger：日誌會標示是 app.services.ingestion 發出的，方便追查
logger = logging.getLogger(__name__)

# ── 上傳限制 ──
# 目前只支援純文字；PDF / Word 需要另外的解析套件（例如 pypdf、python-docx），是之後的擴充點
ALLOWED_SUFFIXES = {".txt", ".md"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB：純文字規章不會更大，上限可以擋掉誤傳的大檔


class DuplicateDocumentError(Exception):
    """同部門已經有內容完全相同的文件（pending 或 ready）；existing_id 讓呼叫端告訴使用者是哪一份。"""

    def __init__(self, existing_id: int):
        """記下已存在的那份文件編號，路由層會把它放進 409 的錯誤訊息。"""
        super().__init__(f"相同內容的文件已存在（id={existing_id}）")
        self.existing_id = existing_id


class InvalidUploadError(ValueError):
    """檔案格式不支援、不是 UTF-8、太大或是空的；路由層會轉成 422。"""


def compute_checksum(raw: bytes) -> str:
    """對檔案原始位元組算 SHA-256（64 個十六進位字元）；內容只差一個字，雜湊就完全不同。"""
    return hashlib.sha256(raw).hexdigest()


def decode_text(raw: bytes) -> str:
    """把上傳的位元組轉成文字；不是 UTF-8 或內容是空的就拋 InvalidUploadError。"""
    # utf-8-sig 會自動去掉 Windows 記事本存檔時加在開頭的 BOM（﻿），一般 utf-8 不會
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        # from e：保留原始例外，除錯時看得到是哪個位元組解不開
        raise InvalidUploadError("檔案不是 UTF-8 文字檔") from e

    # 只有空白或換行也算空檔
    if not text.strip():
        raise InvalidUploadError("檔案內容是空的")
    return text


def _stored_path(checksum: str) -> Path:
    """原始檔依 checksum 存放：同內容只會有一份，重新處理時也找得到。底線開頭代表只給本檔內部使用。"""
    return Path(settings.upload_dir) / f"{checksum}.txt"


def register_upload(
    db: Session,
    *,  # 星號之後的參數都必須用名稱傳入（register_upload(db, title=...)），避免參數順序傳錯
    filename: str,
    raw: bytes,
    dept_id: int,
    title: str,
    version: str,
    level: str,
    source: str | None = None,
    effective_date: date | None = None,
) -> Document:
    """第一段：驗證、擋重複、存檔、建立 pending 主檔。很快，可以在請求裡同步做完。"""
    # ── 1. 驗證：還沒動資料庫之前，先把所有會失敗的檢查做完 ──
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise InvalidUploadError("目前只支援 .txt / .md 純文字檔")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidUploadError("檔案超過 5 MB")
    decode_text(raw)  # 只為了驗證；真正切塊在背景做

    # ── 2. 擋重複 ──
    checksum = compute_checksum(raw)

    # 只和 pending / ready 比：failed 與 deprecated 的同內容檔案，應該允許重新上傳
    existing_id = db.scalar(  # scalar：只取第一列的第一個欄位，沒有資料時回傳 None
        select(Document.id).where(
            Document.dept_id == dept_id,
            Document.checksum == checksum,
            Document.status.in_(("pending", "ready")),
        )
    )
    if existing_id is not None:
        raise DuplicateDocumentError(existing_id)

    # ── 3. 存原始檔 ──
    # 先存檔再建主檔：主檔存在就保證背景處理找得到檔案
    path = _stored_path(checksum)
    path.parent.mkdir(parents=True, exist_ok=True)  # 資料夾不存在就建立；已存在不報錯
    path.write_bytes(raw)

    # ── 4. 建立 pending 主檔並 commit ──
    document = Document(
        dept_id=dept_id,
        title=title,
        version=version,
        level=level,
        source=source or filename,  # 沒填來源就用檔名
        effective_date=effective_date,
        checksum=checksum,
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)  # 重新從資料庫讀回：取得資料庫產生的 id 與 created_at
    return document


def process_document(db: Session, document_id: int, llm: LLMService | None = None) -> Document:
    """第二段：切塊、嵌入、寫入。成功回傳 ready 的文件；失敗把文件標成 failed 後把例外拋出去。"""
    # ── 準備模型：llm 參數讓測試可以換成假的模型；平常不傳，就依設定檔建立 ──
    llm = llm or LLMService(
        settings.ollama_base_url,
        settings.embed_model,
        settings.chat_model,
        timeout=settings.llm_timeout,
    )

    # ── 取得要處理的文件 ──
    document = db.get(Document, document_id)  # get：用主鍵查一筆，查不到回傳 None
    if document is None:
        raise LookupError(f"文件 {document_id} 不存在")

    try:
        # ── 1. 讀檔、切塊、嵌入 ──
        text = decode_text(_stored_path(document.checksum).read_bytes())

        # 嵌入全部成功之後才開始寫 chunk，所以不會出現「寫了 3 塊、第 4 塊嵌入失敗」的半成品
        articles = split_articles(text)
        embeddings = [llm.embed(article.content) for article in articles]

        # ── 2. 寫入 chunk（尚未 commit）──
        # 重新處理時可能已有舊 chunk（例如上次寫到一半），先清掉，避免 chunk_index 重複
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        db.add_all(
            DocumentChunk(
                document_id=document_id,
                chunk_index=index,  # 在文件中的順序，從 0 開始
                article_no=article.article_no,
                content=article.content,
                embedding=embedding,
            )
            # zip：把第 i 個條文與第 i 個向量配成一對；enumerate：同時拿到順序編號
            for index, (article, embedding) in enumerate(zip(articles, embeddings))
        )

        # ── 3. 新版本上線：作廢舊版（尚未 commit）──
        # 同部門、同標題、比較早上傳（id 較小）、仍是 ready 的舊版本一併作廢。
        # 和「新版改成 ready」在同一個 commit，所以檢索看到的要嘛是舊版、要嘛是新版，
        # 不會兩版同時出現，也不會有兩版都查不到的空窗。
        db.execute(
            update(Document)
            .where(
                Document.dept_id == document.dept_id,
                Document.title == document.title,
                Document.status == "ready",
                Document.id < document_id,
            )
            .values(status="deprecated")
        )

        # ── 4. 一次 commit：chunk、新版 ready、舊版 deprecated 同時生效 ──
        document.status = "ready"
        db.commit()
    except Exception:
        # ── 失敗處理：rollback 丟掉未提交的 chunk 與作廢動作，再把主檔標成 failed 保留紀錄 ──
        db.rollback()
        # rollback 之後 document 物件的狀態已失效，所以直接下 UPDATE，不透過物件屬性
        db.execute(update(Document).where(Document.id == document_id).values(status="failed"))
        db.commit()
        raise  # 不吞掉例外：呼叫端（背景工作入口或測試）要知道失敗了

    return document


@contextmanager
def session_scope() -> Iterator[Session]:
    """背景工作用的 session：請求的 session 在回應送出後就關了，背景工作要自己開一個。"""
    db = SessionLocal()
    try:
        yield db  # with session_scope() as db: 的 db 就是這裡 yield 出去的
    finally:
        db.close()  # 不管成功或失敗都要歸還連線，否則連線池會被耗盡


def run_processing(document_id: int) -> None:
    """給 FastAPI BackgroundTasks 呼叫的入口：背景工作的例外沒有人接，所以在這裡記錄下來。"""
    with session_scope() as db:
        try:
            process_document(db, document_id)
        except Exception:
            # logger.exception 會連同完整的錯誤堆疊一起記錄；文件已在 process_document 裡標成 failed
            logger.exception("文件 %s 處理失敗，已標記為 failed", document_id)


def mark_interrupted_as_failed(db: Session) -> int:
    """
    伺服器啟動時呼叫：上次關機時還在處理的文件會永遠卡在 pending（背景工作已經不存在了），
    把它們標成 failed，管理員才能在介面上按「重新處理」。回傳被標記的筆數。
    """
    result = db.execute(update(Document).where(Document.status == "pending").values(status="failed"))
    db.commit()
    return result.rowcount  # rowcount：這個 UPDATE 實際改了幾列


def deprecate_document(db: Session, document: Document) -> Document:
    """作廢：保留紀錄與 chunk，但檢索只看 status='ready'，所以不會再被查到。"""
    document.status = "deprecated"
    db.commit()
    return document
