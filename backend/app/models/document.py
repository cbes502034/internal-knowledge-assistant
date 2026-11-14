"""文件與段落。"""
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Index,
                        Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

EMBED_DIM = 1024   # bge-m3 的向量維度；換模型要一起改並重建向量


class Document(Base):
    """一份法規或 SOP 的一個版本，帶有權限等級與處理狀態。"""
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("level IN ('public', 'dept', 'restricted')", name="ck_documents_level"),
        CheckConstraint("status IN ('pending', 'ready', 'failed', 'deprecated')", name="ck_documents_status"),
        UniqueConstraint("title", "version", name="uq_documents_title_version"),
        Index("ix_documents_filter", "status", "level", "dept_id"),   # 權限過濾用
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(500))          # 來源網址或檔案路徑
    version: Mapped[str] = mapped_column(String(30), default="v1")
    level: Mapped[str] = mapped_column(String(20), default="public")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    checksum: Mapped[str | None] = mapped_column(String(64))         # 檔案 SHA-256
    effective_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """文件依「條」切出的檢索單位，是向量搜尋的對象。"""
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "article_no", name="uq_chunks_document_article"),
        Index("ix_chunks_embedding_hnsw", "embedding",
              postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    article_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))     # 內容未變則沿用既有向量
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")
