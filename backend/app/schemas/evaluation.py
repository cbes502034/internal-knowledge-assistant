"""【檔案用途】評測 API 的回應格式（欄位名稱對齊 frontend/js/app.js 的評測頁）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvalRunResponse(BaseModel):
    """一個評測批次；metrics 跑完才有值。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: Literal["running", "done", "failed"]
    embed_model: str
    config: dict | None
    metrics: dict | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class EvalResultResponse(BaseModel):
    """批次裡的一題。前端用 case_id 顯示題號，資料庫欄位叫 case_no，用 validation_alias 對上。"""
    model_config = ConfigDict(from_attributes=True)

    case_id: int = Field(validation_alias="case_no")
    question: str
    kind: Literal["answer", "refuse", "permission"]
    expected: str | None
    hit_rank: int | None
    refused: bool
    top_hit: str | None
    answer: str | None
    latency_ms: int
