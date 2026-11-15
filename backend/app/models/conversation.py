"""
對話紀錄：對話（conversations）→ 訊息（messages）→ 出處（message_citations）三層。
對應職缺：PostgreSQL 資料表設計、一對多關聯、刪除連動（CASCADE / SET NULL）。

前端 frontend/js/app.js 會用到的欄位都在這裡：
  對話列表要 id、title；訊息要 role、content、refused、latency_ms、feedback；
  出處卡要 rank、doc_title、version、article_no、score。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    """一段對話：屬於某位使用者，底下有多則訊息。"""
    __tablename__ = "conversations"

    # 用 UUID 而不是流水號：網址會出現 /conversations/{id}，
    # 流水號可以被猜（改成 id+1 就去試別人的對話），UUID 猜不到（但權限檢查仍然要做）
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        comment="對話編號（UUID）",
    )

    # 使用者被刪除時，他的對話一併刪除（CASCADE）：對話是個人資料，沒有主人就沒有保留意義
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,  # 「列出我的對話」是最常見的查詢，依 user_id 查要有索引
        comment="對話擁有者",
    )

    title: Mapped[str | None] = mapped_column(String(100), comment="對話標題；前端以第一個問題的前段當標題")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="建立時間",
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,  # 刪除交給資料庫的 ON DELETE CASCADE，不用先把訊息全部載入
        order_by="Message.id",  # 讀取時固定照發送順序
    )

    __table_args__ = ({"comment": "對話"},)


class Message(Base):
    """一則訊息：使用者的提問或助理的回答。"""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="訊息編號")

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        comment="所屬對話",
    )

    role: Mapped[str] = mapped_column(String(10), comment="user：使用者提問 / assistant：助理回答")
    content: Mapped[str] = mapped_column(Text, comment="訊息內容")

    # 以下三個欄位只有 assistant 訊息有意義，user 訊息維持預設值
    refused: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        comment="是否拒答（找不到依據）；統計拒答率、找出知識庫缺口用",
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="從收到問題到產生回答花了幾毫秒")
    feedback: Mapped[str | None] = mapped_column(String(4), comment="使用者回饋：up / down / 未評")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="建立時間",
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list[MessageCitation]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MessageCitation.rank",
    )

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role_valid"),
        # NULL 代表還沒評；CHECK 遇到 NULL 會視為通過，所以不用另外寫 OR feedback IS NULL
        CheckConstraint("feedback IN ('up', 'down')", name="ck_messages_feedback_valid"),
        {"comment": "對話訊息"},
    )


class MessageCitation(Base):
    """
    回答的出處：這則回答當時參考了哪些條文。

    為什麼除了 chunk_id 還要另外存一份 doc_title、version、article_no（快照）？
    文件之後可能改版、作廢甚至刪除，chunk 會跟著消失；但「當時的回答依據的是哪一版的哪一條」
    是稽核需要的事實，不能因為文件更新就跟著改變或消失。
    """
    __tablename__ = "message_citations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="出處編號")

    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        comment="所屬回答",
    )

    # chunk 被刪除時設成 NULL 而不是連帶刪除出處：快照欄位還在，出處紀錄就還有意義
    chunk_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        comment="參考的切塊；切塊被刪除後為 NULL",
    )

    rank: Mapped[int] = mapped_column(SmallInteger, comment="在這次回答裡的排名（1 開始）")
    doc_title: Mapped[str] = mapped_column(String(255), comment="快照：文件標題")
    version: Mapped[str | None] = mapped_column(String(30), comment="快照：文件版本")
    article_no: Mapped[str | None] = mapped_column(String(50), comment="快照：條號，例如 第3條")
    score: Mapped[float | None] = mapped_column(Float, comment="向量相似度；只由關鍵字檢索找到的為 NULL")

    message: Mapped[Message] = relationship(back_populates="citations")

    __table_args__ = ({"comment": "回答出處"},)
