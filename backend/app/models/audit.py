"""
稽核紀錄與 refresh token。
對應職缺：資訊安全、OAuth 2.0、內部系統的可追溯性。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """
    稽核紀錄：誰、在什麼時間、從哪裡、做了什麼事、對象是什麼。

    刻意「不存」問題內容與文件本文：稽核要回答的是「誰做了什麼」，
    把機密內容也抄一份進日誌，等於多了一個可能外洩的地方。要看提問內容，請到 messages 查（有權限控管）。
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="紀錄編號")

    # 可為 NULL：例如用不存在的帳號登入失敗，也要記，但沒有對應的使用者。
    # 使用者被刪除時設成 NULL 而不是刪除紀錄：稽核紀錄不能因為人被刪就跟著消失
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        comment="操作者；未登入或已刪除為 NULL",
    )

    action: Mapped[str] = mapped_column(
        String(50),
        comment="事件，例如 login.success、login.failed、ask、document.upload、user.update",
    )
    target: Mapped[str | None] = mapped_column(String(100), comment="對象類型與編號，例如 document:12")

    # INET 是 PostgreSQL 專門存 IP 的型別：會驗證格式，也能用網段查詢（例如 ip << '10.0.0.0/8'）
    ip: Mapped[str | None] = mapped_column(INET, comment="來源 IP")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,  # 稽核頁面一律依時間倒序列出
        comment="發生時間",
    )

    __table_args__ = ({"comment": "稽核紀錄（只新增、不修改）"},)


class RefreshToken(Base):
    """
    refresh token：access token 只有 15 分鐘，過期後用它換新的，使用者不必重新登入。

    只存雜湊、不存 token 本身：資料庫外洩時，攻擊者拿到的雜湊無法直接拿來換 access token。
    （和密碼存 Argon2 雜湊是同一個道理；這裡用 SHA-256 就夠，因為 token 本身是夠長的亂數，不怕暴力猜。）
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="編號")

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        comment="token 擁有者",
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, comment="token 的 SHA-256 雜湊")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="到期時間")

    # 登出或偵測到異常時填上時間；有值就代表這個 token 已經作廢（保留紀錄，不直接刪除）
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="撤銷時間")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="簽發時間",
    )

    __table_args__ = ({"comment": "refresh token（只存雜湊）"},)
