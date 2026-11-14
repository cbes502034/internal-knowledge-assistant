from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Python 端的預設時間：物件寫入後屬性立刻有值，不必再向資料庫讀一次。"""
    return datetime.now(timezone.utc)
