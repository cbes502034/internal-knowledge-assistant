"""
文件入庫：把一份上傳的文件變成「可被檢索的 chunk」。
對應職缺：RAG 應用開發（資料前處理、向量化）、PostgreSQL 交易與資料一致性。

整個流程拆成兩段，因為嵌入很慢（每塊都要呼叫模型），不能讓上傳的 HTTP 請求一直等：
  第一段 register_upload（在請求裡，很快）：檢查格式與重複 → 存檔 → 建立 pending 主檔 → 立刻回應 202
  第二段 process_document（在背景）：切塊 → 逐塊嵌入 → 一次寫入 chunk 並改成 ready；失敗就標 failed

設計重點，面試最常被問：
  1. checksum：用「內容」判斷重複，不是用檔名或版本號。
  2. 狀態機 pending → ready / failed：中途失敗不會留下「半份文件」被檢索到，也不會讓文件憑空消失。
  3. 交易邊界：嵌入全部成功才寫 chunk；新版 ready 與舊版 deprecated 在同一個 commit。

套件提示：hashlib（SHA-256）、pathlib（存檔）、SQLAlchemy Session（commit / rollback）。
"""

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.chunker import split_articles
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.llm_service import LLMService
from app.models.document import Document, DocumentChunk

logger = logging.getLogger(__name__)

# 目前只支援純文字；PDF / Word 需要另外的解析套件（例如 pypdf、python-docx），是之後的擴充點
ALLOWED_SUFFIXES = {".txt", ".md"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB：純文字規章不會更大，上限可以擋掉誤傳的大檔


class DuplicateDocumentError(Exception):
    """同部門已經有內容完全相同的文件（pending 或 ready）；existing_id 讓呼叫端告訴使用者是哪一份。"""

    def __init__(self, existing_id: int):
        super().__init__(f"相同內容的文件已存在（id={existing_id}）")
        self.existing_id = existing_id


class InvalidUploadError(ValueError):
    """檔案格式不支援、不是 UTF-8、太大或是空的。"""


def compute_checksum(raw: bytes) -> str:
    """對檔案原始位元組算 SHA-256（64 個十六進位字元）；內容只差一個字，雜湊就完全不同。"""
    return hashlib.sha256(raw).hexdigest()


def decode_text(raw: bytes) -> str:
    """把上傳的位元組轉成文字。utf-8-sig 會自動去掉 Windows 記事本存檔時加的 BOM。"""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise InvalidUploadError("檔案不是 UTF-8 文字檔") from e
    if not text.strip():
        raise InvalidUploadError("檔案內容是空的")
    return text


def _stored_path(checksum: str) -> Path:
    """原始檔依 checksum 存放：同內容只會有一份，重新處理時也找得到。"""
    return Path(settings.upload_dir) / f"{checksum}.txt"


def register_upload(
    db: Session,
    *,
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
    # 還沒動資料庫之前，先把所有會失敗的檢查做完
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise InvalidUploadError("目前只支援 .txt / .md 純文字檔")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidUploadError("檔案超過 5 MB")
    decode_text(raw)  # 只為了驗證；真正切塊在背景做

    checksum = compute_checksum(raw)

    # 只和 pending / ready 比：failed 與 deprecated 的同內容檔案，應該允許重新上傳
    existing_id = db.scalar(
        select(Document.id).where(
            Document.dept_id == dept_id,
            Document.checksum == checksum,
            Document.status.in_(("pending", "ready")),
        )
    )
    if existing_id is not None:
        raise DuplicateDocumentError(existing_id)

    # 先存檔再建主檔：主檔存在就保證背景處理找得到檔案
    path = _stored_path(checksum)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)

    document = Document(
        dept_id=dept_id,
        title=title,
        version=version,
        level=level,
        source=source or filename,
        effective_date=effective_date,
        checksum=checksum,
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def process_document(db: Session, document_id: int, llm: LLMService | None = None) -> Document:
    """第二段：切塊、嵌入、寫入。成功回傳 ready 的文件；失敗把文件標成 failed 後把例外拋出去。"""
    llm = llm or LLMService(
        settings.ollama_base_url,
        settings.embed_model,
        settings.chat_model,
        timeout=settings.llm_timeout,
    )

    document = db.get(Document, document_id)
    if document is None:
        raise LookupError(f"文件 {document_id} 不存在")

    try:
        text = decode_text(_stored_path(document.checksum).read_bytes())

        # 嵌入全部成功之後才開始寫 chunk，所以不會出現「寫了 3 塊、第 4 塊嵌入失敗」的半成品
        articles = split_articles(text)
        embeddings = [llm.embed(article.content) for article in articles]

        # 重新處理時可能已有舊 chunk（例如上次寫到一半），先清掉，避免 chunk_index 重複
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        db.add_all(
            DocumentChunk(
                document_id=document_id,
                chunk_index=index,
                article_no=article.article_no,
                content=article.content,
                embedding=embedding,
            )
            for index, (article, embedding) in enumerate(zip(articles, embeddings))
        )

        # 新版本上線：同部門、同標題、比較早上傳、仍是 ready 的舊版本一併作廢。
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

        document.status = "ready"
        db.commit()
    except Exception:
        # 任何一步出錯：rollback 丟掉未提交的 chunk 與作廢動作，再把主檔標成 failed 保留紀錄
        db.rollback()
        db.execute(update(Document).where(Document.id == document_id).values(status="failed"))
        db.commit()
        raise

    return document


@contextmanager
def session_scope() -> Iterator[Session]:
    """背景工作用的 session：請求的 session 在回應送出後就關了，背景工作要自己開一個。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_processing(document_id: int) -> None:
    """給 FastAPI BackgroundTasks 呼叫的入口：背景工作的例外沒有人接，所以在這裡記錄下來。"""
    with session_scope() as db:
        try:
            process_document(db, document_id)
        except Exception:
            logger.exception("文件 %s 處理失敗，已標記為 failed", document_id)


def mark_interrupted_as_failed(db: Session) -> int:
    """
    伺服器啟動時呼叫：上次關機時還在處理的文件會永遠卡在 pending（背景工作已經不存在了），
    把它們標成 failed，管理員才能在介面上按「重新處理」。回傳被標記的筆數。
    """
    result = db.execute(update(Document).where(Document.status == "pending").values(status="failed"))
    db.commit()
    return result.rowcount


def deprecate_document(db: Session, document: Document) -> Document:
    """作廢：保留紀錄與 chunk，但檢索只看 status='ready'，所以不會再被查到。"""
    document.status = "deprecated"
    db.commit()
    return document
