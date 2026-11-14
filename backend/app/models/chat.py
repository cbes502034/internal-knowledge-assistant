"""對話、訊息、出處。"""
import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Identity, Integer,
                        REAL, SmallInteger, String, Text, UniqueConstraint, Uuid, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

DEFAULT_TITLE = "新對話"


class Conversation(Base):
    """一位使用者的一串問答。主鍵出現在網址，用 UUID 避免被猜測。"""
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100), default=DEFAULT_TITLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    """對話中的每一則提問與 AI 回覆。"""
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        CheckConstraint("feedback IS NULL OR feedback IN ('up', 'down')", name="ck_messages_feedback"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)    # 是否回覆「找不到相關規定」
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    feedback: Mapped[str | None] = mapped_column(String(4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list["MessageCitation"]] = relationship(
        cascade="all, delete-orphan", order_by="MessageCitation.rank")


class MessageCitation(Base):
    """一則回覆引用了哪些段落（訊息與段落的多對多中介表）。

    doc_title、version、article_no、locator 是引用當下的快照：文件重新處理後段落會被重建，
    chunk_id 變成空值，但舊對話的出處仍然看得到。
    """
    __tablename__ = "message_citations"
    __table_args__ = (
        UniqueConstraint("message_id", "rank", name="uq_citations_message_rank"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    doc_title: Mapped[str] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(30))
    article_no: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str | None] = mapped_column(String(20))         # 顯示用：第15-1條、第3段
    rank: Mapped[int] = mapped_column(SmallInteger)
    score: Mapped[float | None] = mapped_column(REAL)
