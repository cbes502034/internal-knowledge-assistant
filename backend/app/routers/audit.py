"""
【檔案用途】稽核紀錄查詢 API（只有 IT 管理員）。
只提供讀取，沒有修改與刪除的端點：稽核紀錄必須不可竄改。

端點：
  GET /api/v1/audit-logs  依時間倒序列出，可依使用者或事件篩選
"""

from fastapi import APIRouter, Depends, Query  # 端點分組、依賴注入、查詢字串參數
from sqlalchemy import func, select  # 算總數、組查詢
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

from app.core.database import get_db  # 依賴：資料庫 session
from app.core.deps import require_role  # 依賴：限制角色
from app.models.audit import AuditLog  # 稽核紀錄表
from app.models.user import User, UserRole  # 型別註記與角色列舉
from app.schemas.admin import AuditLogResponse  # 稽核紀錄回應格式
from app.schemas.common import Page  # 分頁回應

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit-logs", response_model=Page[AuditLogResponse])
def list_audit_logs(
    user_id: int | None = None,  # 沒有寫 Query(...) 的簡單型別參數，FastAPI 預設當成查詢字串
    action: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.IT_ADMIN)),
):
    """依時間倒序列出；可用 ?user_id=3 或 ?action=login.failed 篩選。"""
    # ── 1. 依條件逐步加上 WHERE ──
    query = select(AuditLog)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)

    # ── 2. 總數與這一頁的資料（id 越大越新）──
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=items, total=total)
