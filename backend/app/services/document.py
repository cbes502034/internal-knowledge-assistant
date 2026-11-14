"""文件上傳、處理、作廢（對應企劃書 圖 5 文件入庫流程圖）。

上傳只負責收檔與建立紀錄（狀態 pending），切塊與向量化放在背景執行，
所以 API 回 202 Accepted：「已受理，處理中」。前端再查詢狀態。
"""
import hashlib
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import chunker
from app.core.llm_service import get_llm
from app.db import SessionLocal
from app.errors import AppError, conflict, not_found
from app.models import Chunk, Department, Document, User
from app.schemas import DocumentPatch
from app.services import audit
from app.services import user as user_service

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}


def list_documents(db: Session, *, status: str | None, dept_code: str | None,
                   limit: int, offset: int) -> tuple[list[Document], int]:
    query = select(Document)
    if status:
        query = query.where(Document.status == status)
    if dept_code:
        query = query.join(Department, Department.id == Document.dept_id).where(Department.code == dept_code)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit).offset(offset))
    return list(items), total


def _get(db: Session, document_id: int) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise not_found("找不到文件")
    return document


def get_detail(db: Session, *, document_id: int) -> dict:
    """單一文件＋段落數。段落數用 COUNT 在資料庫算，不把段落全部載入再數。"""
    document = _get(db, document_id)
    chunk_count = db.scalar(select(func.count()).where(Chunk.document_id == document.id))
    return {**{c.name: getattr(document, c.name) for c in Document.__table__.columns}, "chunk_count": chunk_count}


def upload(db: Session, *, actor: User | None, filename: str, data: bytes, title: str, dept_code: str,
           level: str, version: str, effective_date: date | None, source: str | None = None) -> Document:
    """收檔並建立文件紀錄（pending）。之後由 process_in_background 處理。"""
    settings = get_settings()
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AppError(422, "unsupported_file_type", "只支援 .txt、.md、.pdf")
    if not data:
        raise AppError(422, "empty_file", "檔案是空的")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(413, "file_too_large", f"檔案超過 {settings.max_upload_mb} MB")
    department = user_service.require_department(db, dept_code)

    checksum = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Document.id).where(Document.checksum == checksum)) is not None:
        raise conflict("duplicate_document", "相同內容的文件已經上傳過")
    if db.scalar(select(Document.id).where(Document.title == title, Document.version == version)) is not None:
        raise conflict("duplicate_version", "同名同版本的文件已存在，請改版本號")

    # 檔名用內容雜湊，不用使用者給的檔名：避免 ../ 這類路徑穿越、同名覆蓋與特殊字元問題
    path = settings.upload_dir / f"{checksum}{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    document = Document(dept_id=department.id, title=title.strip(), source=(source or filename)[:500],
                        version=version.strip() or "v1", level=level, status="pending", checksum=checksum,
                        effective_date=effective_date)
    db.add(document)
    db.flush()
    audit.record(db, user=actor, action="document.upload", target=f"document:{document.id}")
    db.commit()
    return document


def _stored_path(document: Document) -> Path:
    for path in get_settings().upload_dir.glob(f"{document.checksum}.*"):
        return path
    raise FileNotFoundError(f"document {document.id} file missing")


def read_text(path: Path) -> str:
    """讀出文件文字。txt 先試 UTF-8，再試 Big5（cp950）——台灣的舊系統很常輸出 Big5。"""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("無法辨識文字編碼")


def _embed_input(document: Document, locator: str, content: str) -> str:
    """送去算向量的文字加上文件名稱與條號：問題提到法規名稱時，向量也能對上。"""
    return f"{document.title} {locator}\n{content}"


def _content_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


def process(db: Session, document: Document) -> Document:
    """處理一份文件。重點是「冪等」：同一份文件處理幾次，結果都一樣。

    1. 狀態改 pending
    2. 解析、切塊、算向量（內容與模型都沒變的段落沿用舊向量，不重算）
    3. 刪掉舊段落、寫入新段落、狀態改 ready —— 同一個交易
    失敗時整筆還原，清除段落並標記 failed；日誌只記文件編號，不記內容。
    """
    llm = get_llm()
    document.status = "pending"
    db.commit()
    try:
        text = read_text(_stored_path(document))
        mode, articles = chunker.parse_document(text)
        if not articles:
            raise ValueError("文件沒有可用的內容")

        old_vectors = {chunk.content_hash: chunk.embedding for chunk in document.chunks if chunk.content_hash}
        inputs = [_embed_input(document, chunker.make_locator(mode, a.article_no, a.sub_no), a.content)
                  for a in articles]
        hashes = [_content_hash(llm.embed_model, item) for item in inputs]
        todo = [i for i, h in enumerate(hashes) if h not in old_vectors]
        new_vectors = dict(zip(todo, llm.embed_many([inputs[i] for i in todo])))

        db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        db.add_all([
            Chunk(document_id=document.id, article_no=a.article_no, sub_no=a.sub_no, content=a.content,
                  content_hash=hashes[i], embedding=new_vectors[i] if i in new_vectors else old_vectors[hashes[i]])
            for i, a in enumerate(articles)
        ])
        document.chunk_mode = mode
        document.status = "ready"
        db.commit()
        logger.info("document processed: document_id=%s chunks=%d embedded=%d",
                    document.id, len(articles), len(todo))
    except Exception:
        db.rollback()
        logger.exception("document processing failed: document_id=%s", document.id)
        db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        document.status = "failed"
        db.commit()
    db.refresh(document)
    return document


def process_in_background(document_id: int) -> None:
    """背景工作用：自己開一個資料庫連線（請求的連線在回應送出後就關了）。"""
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if document is not None and document.status != "deprecated":
            process(db, document)


def request_reprocess(db: Session, *, actor: User, document_id: int) -> Document:
    """重新處理：把狀態改回 pending，由背景工作重做。

    處理中的不能重複送出；已作廢的不能重新處理——處理完會變成 ready，等於偷偷把作廢的文件恢復，
    要恢復請上傳新版本，稽核紀錄才清楚。
    """
    document = _get(db, document_id)
    if document.status == "pending":
        raise conflict("document_processing", "文件正在處理中")
    if document.status == "deprecated":
        raise conflict("document_deprecated", "已作廢的文件不能重新處理，請上傳新版本")
    document.status = "pending"
    audit.record(db, user=actor, action="document.reprocess", target=f"document:{document.id}")
    db.commit()
    return document


def update(db: Session, *, actor: User, document_id: int, patch: DocumentPatch) -> Document:
    """修改等級或作廢。作廢不刪段落：檢索的 SQL 只找 status='ready'，舊對話的出處也還查得到來源。"""
    document = _get(db, document_id)
    changes = patch.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(document, field, value)
    action = "document.deprecate" if changes.get("status") == "deprecated" else "document.update"
    audit.record(db, user=actor, action=action, target=f"document:{document.id}")
    db.commit()
    return document
