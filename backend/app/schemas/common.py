"""共用的回應格式。"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """分頁回應：items 是這一頁的資料，total 是全部筆數（前端用來顯示「共 N 筆」與換頁）。"""
    items: list[T]
    total: int
