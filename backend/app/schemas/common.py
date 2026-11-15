"""
【檔案用途】多個 API 共用的回應格式。目前只有分頁 Page。

用法：response_model=Page[UserDetailResponse] → 回應長這樣 {"items": [...], "total": 123}
"""

# Generic、TypeVar：讓 Page 可以「裝任何型別」，寫 Page[某型別] 時 items 就是那個型別的清單
from typing import Generic, TypeVar

from pydantic import BaseModel  # 所有 Pydantic 格式的父類別：負責驗證與轉 JSON

T = TypeVar("T")  # 型別變數：Page[UserResponse] 時 T 就是 UserResponse


class Page(BaseModel, Generic[T]):
    """分頁回應：items 是這一頁的資料，total 是全部筆數（前端用來顯示「共 N 筆」與換頁）。"""
    items: list[T]
    total: int
