"""文件上傳、處理、作廢（對應企劃書 圖 5 文件入庫流程圖）。"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import Document, User
from app.schemas import DocumentPatch


def list_documents(db: Session, *, status: str | None, dept_code: str | None,
                   limit: int, offset: int) -> tuple[list[Document], int]:
    """TODO：文件列表（分頁、可依狀態與部門篩選），新的在前。"""
    raise NotImplementedError("services.document.list_documents 尚未實作")


def get_detail(db: Session, *, document_id: int) -> dict:
    """TODO：單一文件＋段落數（DocumentDetailOut 需要 chunk_count）。

    提示：段落數用 select(func.count()).where(Chunk.document_id == ...)，不要把段落全部載入再 len()
    """
    raise NotImplementedError("services.document.get_detail 尚未實作")


def upload(db: Session, *, actor: User, filename: str, data: bytes, title: str, dept_code: str,
           level: str, version: str, effective_date: date | None) -> Document:
    """TODO：上傳文件。

    1. 檢查副檔名（先支援 .txt；之後再加 .pdf）與檔案大小上限
    2. checksum = sha256(data)；同 checksum 已存在 → conflict("duplicate_document", ...)
    3. 把檔案存到 data/uploads/（檔名用 checksum，不要用使用者給的檔名——為什麼？）
    4. 建立 Document(status="pending")，commit
    5. 呼叫 process(db, document)
       （目前同步執行即可；量大時改成背景工作，這就是 API 回 202 的原因）
    6. audit.record(db, user=actor, action="document.upload", target=f"document:{id}")
    """
    raise NotImplementedError("services.document.upload 尚未實作")


def process(db: Session, document: Document) -> Document:
    """TODO：處理一份文件。重點是「冪等」：同一份文件處理幾次，結果都一樣。

    1. status = "pending"
    2. 清除這份文件的舊段落
    3. try:
         讀檔 → chunker.split_articles(text) → 每段算 content_hash
         → LLMService().embed(段落內容) → 建立 Chunk
         → status = "ready"
       except:
         rollback、清除寫到一半的段落、status = "failed"、記 log（只記 document_id，不記內容）
    4. commit、回傳 document
    進階：content_hash 與舊段落相同時沿用舊向量，不重新呼叫模型
    """
    raise NotImplementedError("services.document.process 尚未實作")


def reprocess(db: Session, *, actor: User, document_id: int) -> Document:
    """TODO：重新處理。

    1. 取得文件；不存在 → not_found
    2. status 已是 "pending" → conflict("document_processing", "文件正在處理中")
    3. status 是 "deprecated" → 要不要允許？自己決定並寫下理由
    4. process(db, document)；記稽核
    """
    raise NotImplementedError("services.document.reprocess 尚未實作")


def update(db: Session, *, actor: User, document_id: int, patch: DocumentPatch) -> Document:
    """TODO：修改等級或作廢。

    1. 取得文件；不存在 → not_found
    2. 更新 patch 中有值的欄位
    3. 作廢時不刪除段落：檢索的 SQL 已用 status='ready' 排除
    4. commit；記稽核（action="document.deprecate" 或 "document.update"）
    """
    raise NotImplementedError("services.document.update 尚未實作")
