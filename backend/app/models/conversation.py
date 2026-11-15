"""
【檔案用途】對話紀錄的三張資料表（ORM model）。

    conversations（對話）1 ──< N messages（訊息）1 ──< N message_citations（出處）

  - 一段對話屬於一位使用者，底下有多則訊息。
  - 一則訊息是使用者的提問（role=user）或助理的回答（role=assistant）。
  - 一則回答可以有多個出處，記錄「這個回答當時參考了哪幾條條文」。

對應職缺：PostgreSQL 資料表設計、一對多關聯、刪除連動（CASCADE / SET NULL）。

前端 frontend/js/app.js 會用到的欄位都在這裡：
  對話列表要 id、title；訊息要 role、content、refused、latency_ms、feedback；
  出處卡要 rank、doc_title、version、article_no、score。
"""

# 讓型別註記延後解析：Conversation 裡要寫 list[Message]，但 Message 定義在後面，
# 沒有這行的話 Python 執行到那裡會因為 Message 還不存在而報錯
from __future__ import annotations

import uuid  # 產生 UUID（對話的主鍵）
from datetime import datetime  # 型別註記用：created_at 欄位是 datetime

# SQLAlchemy 的「欄位型別」與「約束」：
from sqlalchemy import (
    BigInteger,  # 8 bytes 整數，用在可能很多筆的主鍵（訊息、出處）
    Boolean,  # 布林（refused）
    CheckConstraint,  # CHECK 約束：限制欄位只能填哪些值
    DateTime,  # 時間（搭配 timezone=True 存成 timestamptz）
    Float,  # 浮點數（相似度分數）
    ForeignKey,  # 外鍵：指向另一張表的主鍵，並設定刪除時的行為（ondelete）
    Integer,  # 4 bytes 整數（耗時毫秒）
    SmallInteger,  # 2 bytes 整數（排名，最多幾筆，用小整數就夠）
    String,  # 有長度上限的字串（varchar）
    Text,  # 沒有長度上限的字串（訊息內容）
    Uuid,  # UUID 型別（PostgreSQL 原生 uuid）
    func,  # 呼叫資料庫的函式，例如 func.now() → SQL 的 now()
    text,  # 寫一段原生 SQL，這裡用在 server_default（例如 'false'、gen_random_uuid()）
)
# Mapped：型別註記（Mapped[int] 代表這個屬性對應一個 int 欄位）
# mapped_column：宣告欄位的細節（型別、主鍵、預設值…）
# relationship：宣告 ORM 關聯，讓你可以用 conversation.messages 直接拿到訊息清單
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base  # 所有 model 的共同父類別；繼承它才會被登記成資料表


class Conversation(Base):
    """一段對話：屬於某位使用者，底下有多則訊息。"""
    __tablename__ = "conversations"  # 在資料庫裡的表名

    # ── 主鍵 ──
    # 用 UUID 而不是流水號：網址會出現 /conversations/{id}，
    # 流水號可以被猜（改成 id+1 就去試別人的對話），UUID 猜不到（但權限檢查仍然要做）
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,  # Python 端建立物件時自動產生
        server_default=text("gen_random_uuid()"),  # 直接用 SQL 新增資料時，資料庫自己產生
        comment="對話編號（UUID）",
    )

    # ── 擁有者 ──
    # 使用者被刪除時，他的對話一併刪除（CASCADE）：對話是個人資料，沒有主人就沒有保留意義
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,  # 「列出我的對話」是最常見的查詢，依 user_id 查要有索引
        comment="對話擁有者",
    )

    # ── 一般欄位 ──
    # Mapped[str | None] 代表可以是 NULL：新對話還沒有標題，第一次提問後才自動帶入
    title: Mapped[str | None] = mapped_column(String(100), comment="對話標題；前端以第一個問題的前段當標題")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # 由資料庫填入目前時間，不依賴應用程式伺服器的時鐘
        comment="建立時間",
    )

    # ── ORM 關聯（不是資料庫欄位，是 Python 端的便利屬性）──
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",  # 和 Message.conversation 互相對應，改一邊另一邊同步
        cascade="all, delete-orphan",  # 在 Python 端刪對話時，訊息一起刪
        passive_deletes=True,  # 刪除交給資料庫的 ON DELETE CASCADE，不用先把訊息全部載入
        order_by="Message.id",  # 讀取時固定照發送順序
    )

    # ── 表層級設定 ──
    __table_args__ = ({"comment": "對話"},)


class Message(Base):
    """一則訊息：使用者的提問或助理的回答。"""
    __tablename__ = "messages"

    # ── 主鍵 ──
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="訊息編號")

    # ── 所屬對話 ──
    # 對話被刪除時，訊息一起刪除（CASCADE）
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,  # 「讀取某段對話的所有訊息」要依它查
        comment="所屬對話",
    )

    # ── 內容 ──
    role: Mapped[str] = mapped_column(String(10), comment="user：使用者提問 / assistant：助理回答")
    content: Mapped[str] = mapped_column(Text, comment="訊息內容")

    # ── 只有 assistant 訊息有意義的欄位，user 訊息維持預設值 ──
    refused: Mapped[bool] = mapped_column(
        Boolean,
        default=False,  # Python 端的預設值
        server_default=text("false"),  # 資料庫端的預設值（兩邊都設，不管從哪裡新增都有值）
        comment="是否拒答（找不到依據）；統計拒答率、找出知識庫缺口用",
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="從收到問題到產生回答花了幾毫秒")
    feedback: Mapped[str | None] = mapped_column(String(4), comment="使用者回饋：up / down / 未評")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="建立時間",
    )

    # ── ORM 關聯 ──
    conversation: Mapped[Conversation] = relationship(back_populates="messages")  # message.conversation 取得所屬對話
    citations: Mapped[list[MessageCitation]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MessageCitation.rank",  # 出處依排名排好
    )

    # ── 資料庫層的約束：程式有 bug 時的最後一道防線 ──
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

    # ── 主鍵 ──
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="出處編號")

    # ── 所屬回答：回答被刪除時出處一起刪除 ──
    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        comment="所屬回答",
    )

    # ── 參照：指向當時用到的 chunk ──
    # chunk 被刪除時設成 NULL 而不是連帶刪除出處：快照欄位還在，出處紀錄就還有意義
    chunk_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        comment="參考的切塊；切塊被刪除後為 NULL",
    )

    # ── 快照：寫入當下就固定，之後文件怎麼變都不影響 ──
    rank: Mapped[int] = mapped_column(SmallInteger, comment="在這次回答裡的排名（1 開始）")
    doc_title: Mapped[str] = mapped_column(String(255), comment="快照：文件標題")
    version: Mapped[str | None] = mapped_column(String(30), comment="快照：文件版本")
    article_no: Mapped[str | None] = mapped_column(String(50), comment="快照：條號，例如 第3條")
    score: Mapped[float | None] = mapped_column(Float, comment="向量相似度；只由關鍵字檢索找到的為 NULL")

    # ── ORM 關聯 ──
    message: Mapped[Message] = relationship(back_populates="citations")

    __table_args__ = ({"comment": "回答出處"},)
