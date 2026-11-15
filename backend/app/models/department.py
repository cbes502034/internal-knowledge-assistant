from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User

class Department(Base):
    """部門資料表模型"""
    __tablename__ = "departments"

    # id: smallint PK 部門編號（自動遞增，在 PostgreSQL 對應為 SMALLSERIAL）
    id: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
        autoincrement=True,
        comment="部門編號",
    )

    # code: varchar(20) 唯一 代碼（sales、product、rd、ops、finance、gm_office）
    # 註：使用 Mapped[str] 已預設為 NOT NULL，無需額外寫 nullable=False
    code: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        comment="部門代碼",
    )

    # name: varchar(50) 必填顯示名稱
    name: Mapped[str] = mapped_column(
        String(50),
        comment="顯示名稱",
    )

    users: Mapped[list["User"]] = relationship(back_populates="department")
