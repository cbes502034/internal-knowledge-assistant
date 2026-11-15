from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# bge-m3 的輸出維度；換嵌入模型時，這個數字與 embedding 欄位都要跟著重建
EMBEDDING_DIM = 1024


class Document(Base):
    """文件主檔：一份規章或 SOP 一筆，權限（level / dept_id）與狀態都記在這裡。"""
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="文件編號",
    )

    # 文件所屬部門；level 為 dept 時，只有同部門的人看得到
    dept_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("departments.id", ondelete="RESTRICT"),
        index=True,
        comment="所屬部門",
    )

    title: Mapped[str] = mapped_column(String(255), comment="文件標題")
    source: Mapped[str | None] = mapped_column(String(500), comment="文件來源")
    version: Mapped[str] = mapped_column(String(30), comment="版本")

    # 存取等級：public 全員 / dept 同部門 / restricted 僅 IT 管理員
    level: Mapped[str] = mapped_column(String(20), comment="存取等級：public / dept / restricted")

    # 只有 ready 的文件會被檢索；deprecated 代表已作廢，保留紀錄但不再被查到
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default=text("'pending'"),
        comment="處理狀態：pending / ready / failed / deprecated",
    )

    checksum: Mapped[str | None] = mapped_column(String(64), comment="檔案 SHA-256，用來判斷重複上傳")
    effective_date: Mapped[date | None] = mapped_column(Date, comment="生效日")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="建立時間",
    )

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,  # 刪文件時交給資料庫的 ON DELETE CASCADE，不用先把 chunks 全載入
    )

    __table_args__ = (
        CheckConstraint("level IN ('public', 'dept', 'restricted')", name="ck_documents_level_valid"),
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'deprecated')",
            name="ck_documents_status_valid",
        ),
        {"comment": "文件主檔"},
    )


class DocumentChunk(Base):
    """文件切塊：檢索的最小單位，內文與向量都存在這裡。"""
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="切塊編號",
    )

    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        comment="所屬文件",
    )

    chunk_index: Mapped[int] = mapped_column(Integer, comment="在文件中的順序（從 0 開始）")
    article_no: Mapped[str | None] = mapped_column(String(50), comment="條號，例如 第3條；無條號的文件為段落編號")
    content: Mapped[str] = mapped_column(Text, comment="切塊內文")

    # 資料量大了再加 HNSW 索引（pgvector 的近似最近鄰索引）；目前資料少，全表掃描即可
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), comment="內文向量")

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_index"),
        {"comment": "文件切塊與向量"},
    )
