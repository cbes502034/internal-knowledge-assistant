"""問答相關的請求與回應格式（欄位名稱對齊 frontend/js/app.js）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    # 上限可以擋掉把整份文件貼進來的請求：問題太長會擠掉 prompt 裡參考資料的空間
    content: str = Field(min_length=1, max_length=1000)


class FeedbackRequest(BaseModel):
    value: Literal["up", "down"]


class CitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    doc_title: str
    version: str | None
    article_no: str | None
    score: float | None
    # 原文片段：每次讀取時依「目前」的權限重新檢查，沒權限或原文已刪除就是 None
    preview: str | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    refused: bool
    latency_ms: int | None
    feedback: Literal["up", "down"] | None
    created_at: datetime
    citations: list[CitationResponse] = []
