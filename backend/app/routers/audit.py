"""稽核紀錄查詢（只有 IT 管理員）。只提供讀取，沒有修改與刪除的端點：稽核紀錄必須不可竄改。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.schemas.admin import AuditLogResponse
from app.schemas.common import Page

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit-logs", response_model=Page[AuditLogResponse])
def list_audit_logs(
    user_id: int | None = None,
    action: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.IT_ADMIN)),
):
    """依時間倒序列出；可用 ?user_id=3 或 ?action=login.failed 篩選。"""
    query = select(AuditLog)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=items, total=total)
