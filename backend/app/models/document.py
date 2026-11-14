"""文件與段落。"""
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index,
                        Integer, SmallInteger, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

EMBED_DIM = 1024   # bge-m3 的向量維度；換模型要一起改並重建向量


class Document(Base):
    """一份法規或 SOP 的一個版本，帶有權限等級與處理狀態。"""
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("level IN ('public', 'dept', 'restricted')", name="ck_documents_level"),
        CheckConstraint("status IN ('pending', 'ready', 'failed', 'deprecated')", name="ck_documents_status"),
        CheckConstraint("chunk_mode IN ('article', 'window')", name="ck_documents_chunk_mode"),
        UniqueConstraint("title", "version", name="uq_documents_title_version"),
        Index("ix_documents_filter", "status", "level", "dept_id"),   # 權限過濾用
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(500))          # 來源網址或原始檔名
    version: Mapped[str] = mapped_column(String(30), default="v1")
    level: Mapped[str] = mapped_column(String(20), default="public")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # article：依「第N條」切塊；window：沒有條號的文件改用滑動視窗
    chunk_mode: Mapped[str] = mapped_column(String(10), default="article", server_default="article")
    checksum: Mapped[str | None] = mapped_column(String(64))         # 檔案 SHA-256
    effective_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """檢索單位：依條切塊時一條一筆（第 15-1 條 → article_no=15、sub_no=1）；滑動視窗時一段一筆。"""
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "article_no", "sub_no", name="uq_chunks_document_article_sub"),
        Index("ix_chunks_embedding_hnsw", "embedding",
              postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    article_no: Mapped[int] = mapped_column(Integer)
    sub_no: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))     # 嵌入模型＋內容的雜湊；未變則沿用既有向量
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")
