"""
文件管理 API（只有 IT 管理員能用）：列表、上傳、修改、重新處理。
對應職缺：RESTful API、檔案上傳、背景工作、RBAC。

為什麼上傳回 202 Accepted 而不是 201 Created？
202 的意思是「收到了，但還沒處理完」：主檔已建立（pending），切塊與嵌入在背景進行，
前端看到 202 就知道要稍後重新整理狀態，而不是以為已經可以查了。
"""

from datetime import date
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.department import Department
from app.models.document import Document
from app.models.user import User, UserRole
from app.schemas.admin import DocumentPatch
from app.schemas.common import Page
from app.schemas.document import DocumentLevel, DocumentResponse, DocumentStatus
from app.services import ingestion
from app.services.audit import log_event

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

admin_only = require_role(UserRole.IT_ADMIN)


def _get_document(db: Session, document_id: int) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return document


@router.get("", response_model=Page[DocumentResponse])
def list_documents(
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    """文件列表，新的在前；可用 ?status=failed 只看失敗的。"""
    query = select(Document)
    if status_filter:
        query = query.where(Document.status == status_filter)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Document.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=items, total=total)


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    request: Request,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=255)],
    dept_code: Annotated[str, Form()],
    level: Annotated[DocumentLevel, Form()],
    version: Annotated[str, Form(min_length=1, max_length=30)] = "v1",
    effective_date: Annotated[str | None, Form()] = None,  # 前端沒選日期時會送空字串，所以先收字串再轉
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    """上傳文件（multipart/form-data）：驗證後建立 pending 主檔，切塊與嵌入交給背景工作。"""
    dept = db.scalar(select(Department).where(Department.code == dept_code))
    if dept is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "部門代碼不存在")

    try:
        parsed_date = date.fromisoformat(effective_date) if effective_date else None
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "生效日期格式應為 YYYY-MM-DD")

    # 最多只讀「上限 + 1」個位元組：超過就知道太大，不必把整個大檔讀進記憶體
    raw = file.file.read(ingestion.MAX_UPLOAD_BYTES + 1)

    try:
        document = ingestion.register_upload(
            db,
            filename=file.filename or "",
            raw=raw,
            dept_id=dept.id,
            title=title,
            version=version,
            level=level,
            effective_date=parsed_date,
        )
    except ingestion.InvalidUploadError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    except ingestion.DuplicateDocumentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"相同內容的文件已存在（編號 {e.existing_id}）")

    # 回應送出之後才執行：使用者不用等嵌入跑完
    background.add_task(ingestion.run_processing, document.id)
    log_event(db, request, "document.upload", user_id=admin.id, target=f"document:{document.id}")
    return document


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: int,
    data: DocumentPatch,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    """修改文件資訊或作廢。改 level 會立刻影響誰查得到（權限條件在檢索時才套用）。"""
    document = _get_document(db, document_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(document, field, value)
    db.commit()
    db.refresh(document)
    log_event(db, request, "document.update", user_id=admin.id, target=f"document:{document.id}")
    return document


@router.post("/{document_id}/processing-jobs", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
def reprocess_document(
    document_id: int,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    """
    重新處理失敗的文件（例如當時模型服務掛了）。
    路徑用名詞 processing-jobs：REST 把「重新處理」看成「建立一個處理工作」，而不是在網址裡放動詞。
    """
    document = _get_document(db, document_id)
    if document.status != "failed":
        # pending 代表正在處理，再送一次會變成兩個背景工作同時寫同一份文件
        raise HTTPException(status.HTTP_409_CONFLICT, "只有處理失敗的文件可以重新處理")

    document.status = "pending"
    db.commit()
    db.refresh(document)
    background.add_task(ingestion.run_processing, document.id)
    log_event(db, request, "document.reprocess", user_id=admin.id, target=f"document:{document.id}")
    return document
