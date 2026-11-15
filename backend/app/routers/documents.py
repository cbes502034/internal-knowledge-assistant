"""
【檔案用途】文件管理 API（只有 IT 管理員能用）：列表、上傳、修改、重新處理。
對應職缺：RESTful API、檔案上傳、背景工作、RBAC。

為什麼上傳回 202 Accepted 而不是 201 Created？
202 的意思是「收到了，但還沒處理完」：主檔已建立（pending），切塊與嵌入在背景進行，
前端看到 202 就知道要稍後重新整理狀態，而不是以為已經可以查了。

端點：
  GET   /api/v1/documents                            文件列表（可依狀態篩選）
  POST  /api/v1/documents                            上傳（multipart/form-data）
  PATCH /api/v1/documents/{document_id}              修改資訊或作廢
  POST  /api/v1/documents/{document_id}/processing-jobs  重新處理失敗的文件
"""

from datetime import date  # 把前端送來的日期字串轉成 date
from typing import Annotated  # Annotated[型別, 來源]：標示參數來自 Form、File、Query

from fastapi import (
    APIRouter,  # 端點分組
    BackgroundTasks,  # 背景工作：回應送出之後才執行的函式
    Depends,  # 依賴注入
    File,  # 參數來源：上傳的檔案
    Form,  # 參數來源：multipart 表單裡的文字欄位
    HTTPException,  # 丟出帶狀態碼的錯誤
    Query,  # 參數來源：網址查詢字串（?status=...）
    Request,  # 取 IP 寫稽核
    UploadFile,  # 上傳檔案的型別（有 filename、file 等屬性）
    status,  # 狀態碼常數
)
from sqlalchemy import func, select  # func.count() 算總數；select 組查詢
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.database import get_db  # 依賴：每個請求一個資料庫 session
from app.core.deps import require_role  # 依賴：限制角色
from app.models.department import Department  # 用部門代碼查部門
from app.models.document import Document  # 文件主檔
from app.models.user import User, UserRole  # 型別註記與角色列舉
from app.schemas.admin import DocumentPatch  # 修改文件的格式（status 只能改成 deprecated）
from app.schemas.common import Page  # 分頁回應
from app.schemas.document import DocumentLevel, DocumentResponse, DocumentStatus  # 你寫的文件格式與列舉
from app.services import ingestion  # 入庫流程（整個模組匯入，呼叫時寫 ingestion.xxx，一看就知道來源）
from app.services.audit import log_event  # 寫稽核紀錄

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# 這個檔案的所有端點都只允許 IT 管理員
admin_only = require_role(UserRole.IT_ADMIN)


def _get_document(db: Session, document_id: int) -> Document:
    """用編號取文件，不存在就丟 404；多個端點共用，避免每個都寫一次同樣的檢查。"""
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return document


@router.get("", response_model=Page[DocumentResponse])  # 路徑 "" 加上 prefix 就是 /api/v1/documents
def list_documents(
    # 參數名稱叫 status_filter，避免蓋掉上面匯入的 status 模組；alias 讓網址仍寫 ?status=
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    """文件列表，新的在前；可用 ?status=failed 只看失敗的。"""
    # ── 1. 組查詢條件 ──
    query = select(Document)
    if status_filter:
        query = query.where(Document.status == status_filter)

    # ── 2. 總數：把查詢包成子查詢再 count，篩選條件會跟著套用 ──
    total = db.scalar(select(func.count()).select_from(query.subquery()))

    # ── 3. 這一頁的資料 ──
    items = db.scalars(query.order_by(Document.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=items, total=total)


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    request: Request,
    background: BackgroundTasks,  # FastAPI 自動提供，不用 Depends
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=255)],
    dept_code: Annotated[str, Form()],
    level: Annotated[DocumentLevel, Form()],  # Literal 型別：只能是 public / dept / restricted，其他值自動 422
    version: Annotated[str, Form(min_length=1, max_length=30)] = "v1",
    effective_date: Annotated[str | None, Form()] = None,  # 前端沒選日期時會送空字串，所以先收字串再轉
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    """上傳文件（multipart/form-data）：驗證後建立 pending 主檔，切塊與嵌入交給背景工作。"""
    # ── 1. 部門代碼換成部門 ──
    dept = db.scalar(select(Department).where(Department.code == dept_code))
    if dept is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "部門代碼不存在")

    # ── 2. 日期字串轉成 date（空字串視為沒填）──
    try:
        parsed_date = date.fromisoformat(effective_date) if effective_date else None
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "生效日期格式應為 YYYY-MM-DD")

    # ── 3. 讀檔 ──
    # 最多只讀「上限 + 1」個位元組：超過就知道太大，不必把整個大檔讀進記憶體
    raw = file.file.read(ingestion.MAX_UPLOAD_BYTES + 1)

    # ── 4. 第一段入庫（驗證、擋重複、建 pending 主檔），服務層的例外轉成 HTTP 錯誤 ──
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

    # ── 5. 第二段入庫交給背景：回應送出之後才執行，使用者不用等嵌入跑完 ──
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
    # exclude_unset=True：只改有送來的欄位
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
    # ── 1. 只有 failed 可以重新處理 ──
    document = _get_document(db, document_id)
    if document.status != "failed":
        # pending 代表正在處理，再送一次會變成兩個背景工作同時寫同一份文件
        raise HTTPException(status.HTTP_409_CONFLICT, "只有處理失敗的文件可以重新處理")

    # ── 2. 改回 pending 並排入背景 ──
    document.status = "pending"
    db.commit()
    db.refresh(document)
    background.add_task(ingestion.run_processing, document.id)
    log_event(db, request, "document.reprocess", user_id=admin.id, target=f"document:{document.id}")
    return document
