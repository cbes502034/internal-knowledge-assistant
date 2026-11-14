"""API 的請求與回應格式（對應企劃書 7.5）。"""
import uuid
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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
    role: Literal["employee", "manager", "it_admin"]
    is_active: bool
    department: DepartmentOut
    last_active_at: datetime | None = None


# ---------- 對話 ----------
class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=100)


class ConversationOut(ORMModel):
    id: uuid.UUID
    title: str
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("問題不能是空白")
        return value.strip()


class CitationOut(ORMModel):
    rank: int
    doc_title: str
    version: str | None
    article_no: int
    locator: str | None
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
    chunk_mode: Literal["article", "window"]
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
    """沒填的參數用目前的系統設定。"""
    mode: Literal["hybrid", "vector", "keyword"] | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    threshold: float | None = Field(default=None, ge=0, le=1)
    keyword_weight: float | None = Field(default=None, ge=0, le=1)


class EvalMetrics(BaseModel):
    cases: int
    hit_at_1: float
    hit_at_3: float
    mrr: float
    false_refusal_rate: float
    refuse_accuracy: float
    permission_pass: float
    leaks: int
    p50_ms: int
    p95_ms: int


class EvalRunOut(BaseModel):
    id: int
    embed_model: str
    config: dict | None
    started_at: datetime
    finished_at: datetime | None
    metrics: EvalMetrics | None = None


class EvalResultOut(BaseModel):
    case_id: int
    question: str
    kind: Literal["answer", "refuse", "permission"]
    expected: str | None
    as_dept: str
    as_role: str
    hit_rank: int | None
    refused: bool
    leaked: bool
    top_hit: str | None
    latency_ms: int | None


# ---------- 稽核 ----------
class AuditLogOut(ORMModel):
    id: int
    user_id: int | None
    action: str
    target: str | None
    ip: str | None
    created_at: datetime

    @field_validator("ip", mode="before")
    @classmethod
    def _ip_to_str(cls, value):
        return None if value is None else str(value)     # 資料庫回傳的是 ipaddress 物件
