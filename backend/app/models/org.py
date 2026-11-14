"""部門、使用者、更新權杖。"""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Identity,
                        SmallInteger, String, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Department(Base):
    """權限的基本單位，對應組織圖的五大單位與總經理室。"""
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)      # sales、product、rd、ops、finance、gm_office
    name: Mapped[str] = mapped_column(String(50))


class User(Base):
    """登入帳號；正式環境由 AD 同步。"""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('employee', 'manager', 'it_admin')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))          # Argon2id 雜湊，不存明文
    role: Mapped[str] = mapped_column(String(20), default="employee")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # 閒置判斷用
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    department: Mapped[Department] = relationship()


class RefreshToken(Base):
    """更新權杖：只存雜湊；登出與閒置時填入 revoked_at。"""
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 十六進位
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
