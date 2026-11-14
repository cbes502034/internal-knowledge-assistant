"""稽核紀錄：只新增、不修改、不刪除。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(db: Session, *, user: User | None, action: str, target: str | None = None,
           ip: str | None = None) -> None:
    """TODO：寫入一筆稽核紀錄。

    1. db.add(AuditLog(user_id=..., action=action, target=target, ip=ip))
    2. commit
    注意：不要把提問內容、文件內容寫進 target
    思考：稽核寫入失敗時，原本的操作要不要跟著失敗？
    """
    raise NotImplementedError("services.audit.record 尚未實作")


def list_logs(db: Session, *, user_id: int | None, since: datetime | None, until: datetime | None,
              limit: int, offset: int) -> tuple[list[AuditLog], int]:
    """TODO：稽核紀錄查詢（新的在前），可依使用者與時間範圍篩選。回傳 (這一頁, 總筆數)。"""
    raise NotImplementedError("services.audit.list_logs 尚未實作")
