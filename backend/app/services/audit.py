"""稽核紀錄：只新增、不修改、不刪除。"""
import ipaddress
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog


def _valid_ip(ip: str | None) -> str | None:
    """欄位型別是 INET，不是合法位址（例如測試用戶端的 'testclient'）就不存。"""
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def record(db: Session, *, user, action: str, target: str | None = None, ip: str | None = None) -> None:
    """加入一筆稽核紀錄，但「不」commit。

    由呼叫端在同一個交易中一起 commit：業務變更與稽核紀錄要嘛都成功、要嘛都失敗，
    不會出現「操作做了卻沒有紀錄」的情況。
    注意：target 只放對象類型與編號，不放提問內容或文件內容。
    """
    db.add(AuditLog(user_id=getattr(user, "id", None), action=action, target=target, ip=_valid_ip(ip)))


def list_logs(db: Session, *, user_id: int | None, since: datetime | None, until: datetime | None,
              limit: int, offset: int) -> tuple[list[AuditLog], int]:
    """稽核紀錄查詢（新的在前），可依使用者與時間範圍篩選。回傳 (這一頁, 總筆數)。"""
    query = select(AuditLog)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if since is not None:
        query = query.where(AuditLog.created_at >= since)
    if until is not None:
        query = query.where(AuditLog.created_at < until)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset))
    return list(items), total
