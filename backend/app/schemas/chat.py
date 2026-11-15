"""
【檔案用途】問答相關的請求與回應格式（欄位名稱對齊 frontend/js/app.js）。
  AskRequest        提問的請求內容
  FeedbackRequest   回饋的請求內容
  CitationResponse  一個出處
  MessageResponse   一則訊息（含出處）

Pydantic 在這裡做兩件事：請求進來時驗證（不合格自動回 422）、回應出去時只輸出宣告的欄位。
"""

from datetime import datetime  # 型別：建立時間
from typing import Literal  # Literal["up", "down"]：值只能是列出的其中一個

# BaseModel：格式的父類別；ConfigDict：設定（例如可從 ORM 物件讀值）；Field：欄位限制（長度、範圍）
from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    """提問：只有問題內容。"""
    # 上限可以擋掉把整份文件貼進來的請求：問題太長會擠掉 prompt 裡參考資料的空間
    content: str = Field(min_length=1, max_length=1000)


class FeedbackRequest(BaseModel):
    """回饋：只能是 up（有用）或 down（沒用），其他值自動 422。"""
    value: Literal["up", "down"]


class CitationResponse(BaseModel):
    """一個出處：出處表的快照欄位，加上依目前權限決定給不給看的原文。"""
    # from_attributes=True：可以直接用 ORM 物件（MessageCitation）建立，不用先轉成 dict
    model_config = ConfigDict(from_attributes=True)

    rank: int
    doc_title: str
    version: str | None
    article_no: str | None
    score: float | None
    # 原文片段：每次讀取時依「目前」的權限重新檢查，沒權限或原文已刪除就是 None
    preview: str | None = None


class MessageResponse(BaseModel):
    """一則訊息；citations 會自動從 Message.citations 關聯讀出並逐筆轉成 CitationResponse。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    refused: bool
    latency_ms: int | None
    feedback: Literal["up", "down"] | None
    created_at: datetime
    citations: list[CitationResponse] = []  # 使用者的提問沒有出處，預設空清單
