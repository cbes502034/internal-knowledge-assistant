from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DocumentLevel = Literal["public", "dept", "restricted"]

DocumentStatus = Literal[
    "pending",
    "ready",
    "failed",
    "deprecated",
]


class DocumentCreate(BaseModel):
    dept_id: int
    title: str = Field(min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=500)
    version: str = Field(min_length=1, max_length=30)
    level: DocumentLevel
    effective_date: date | None = None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=500)
    version: str | None = Field(default=None, max_length=30)
    level: DocumentLevel | None = None
    status: DocumentStatus | None = None
    effective_date: date | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dept_id: int
    title: str
    source: str | None
    version: str
    level: DocumentLevel
    status: DocumentStatus
    checksum: str | None
    effective_date: date | None