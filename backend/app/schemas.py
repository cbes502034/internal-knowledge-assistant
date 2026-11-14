"""API 的請求與回應格式（對應企劃書 7.5）。"""
import uuid
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # 可直接由 SQLAlchemy 物件轉換


class Page(BaseModel, Generic[T]):
    """列表統一格式。"""
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------- 驗證 ----------
class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int                      # 秒


# ---------- 部門、使用者 ----------
class DepartmentOut(ORMModel):
    id: int
    code: str
    name: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    dept_code: str


class UserPatch(BaseModel):
    dept_code: str | None = None
    role: Literal["employee", "manager", "it_admin"] | None = None
    is_active: bool | None = None


class UserOut(ORMModel):
    id: int
    email: EmailStr
    role: str
    is_active: bool
    department: DepartmentOut


# ---------- 對話 ----------
class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=100)


class ConversationOut(ORMModel):
    id: uuid.UUID
    title: str
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class CitationOut(ORMModel):
    rank: int
    doc_title: str
    version: str | None
    article_no: int
    score: float | None


class MessageOut(ORMModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    refused: bool
    latency_ms: int | None
    feedback: Literal["up", "down"] | None
    citations: list[CitationOut] = []
    created_at: datetime


class FeedbackIn(BaseModel):
    value: Literal["up", "down"] | None


# ---------- 文件 ----------
class DocumentOut(ORMModel):
    id: int
    title: str
    version: str
    level: Literal["public", "dept", "restricted"]
    status: Literal["pending", "ready", "failed", "deprecated"]
    source: str | None
    effective_date: date | None
    dept_id: int
    created_at: datetime


class DocumentDetailOut(DocumentOut):
    chunk_count: int


class DocumentPatch(BaseModel):
    level: Literal["public", "dept", "restricted"] | None = None
    status: Literal["deprecated"] | None = None      # 只允許由 API 改成作廢


# ---------- 評測 ----------
class EvalRunCreate(BaseModel):
    embed_model: str | None = None       # 不填則用設定檔的模型
    config: dict | None = None


class EvalMetrics(BaseModel):
    hit_at_1: float
    hit_at_3: float
    mrr: float
    refuse_accuracy: float
    p50_ms: int
    p95_ms: int


class EvalRunOut(ORMModel):
    id: int
    embed_model: str
    config: dict | None
    started_at: datetime
    finished_at: datetime | None
    metrics: EvalMetrics | None = None


class EvalResultOut(ORMModel):
    case_id: int
    question: str
    hit_rank: int | None
    refused: bool
    latency_ms: int | None


# ---------- 稽核 ----------
class AuditLogOut(ORMModel):
    id: int
    user_id: int | None
    action: str
    target: str | None
    ip: str | None
    created_at: datetime
