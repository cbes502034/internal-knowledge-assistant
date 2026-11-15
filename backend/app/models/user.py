from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.orm import (
    Mapped, 
    mapped_column, 
    relationship
)

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.department import Department


class UserRole(StrEnum):
    """使用者角色權限列舉"""
    EMPLOYEE = "employee"  # 一般員工
    MANAGER = "manager"    # 部門主管
    IT_ADMIN = "it_admin"  # IT 管理員


class User(Base):
    __tablename__ = "users"

    # id: bigint PK 使用者編號（自動遞增）
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="使用者編號",
    )

    # dept_id: smallint FK、必填 所屬部門，決定可查詢的文件範圍
    dept_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("departments.id", ondelete="RESTRICT"),
        index=True,
        comment="所屬部門，決定可查詢的文件範圍",
    )

    # email: varchar(255) 唯一 登入帳號
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        comment="登入帳號",
    )

    # password_hash: varchar(255) 必填 Argon2id 雜湊，不存明文
    password_hash: Mapped[str] = mapped_column(
        String(255),
        comment="Argon2id 雜湊，不存明文",
    )

    # role: varchar(20) 限定值 employee／manager／it_admin
    role: Mapped[str] = mapped_column(
        String(20),
        default=UserRole.EMPLOYEE.value,
        server_default=text("'employee'"),
        comment="角色權限：employee / manager / it_admin",
    )

    # is_active: boolean 預設 true 停用後無法登入，保留歷史紀錄
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        comment="是否啟用（停用後無法登入，保留歷史紀錄）",
    )

    # last_active_at: timestamptz 最後操作時間，用於閒置判斷
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="最後操作時間，用於閒置判斷",
    )

    # ORM 關聯設定：透過 user.department 直接取得所屬部門物件
    department: Mapped[Department] = relationship(back_populates="users")

    # 資料表層級約束：嚴格限制 role 只能寫入指定的三個角色字串
    __table_args__ = (
        CheckConstraint(
            "role IN ('employee', 'manager', 'it_admin')",
            name="ck_users_role_valid",
        ),
        {"comment": "系統使用者資料表"},
    )
