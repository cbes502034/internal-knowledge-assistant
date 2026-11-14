"""把文件切成檢索單位。

對應職缺：RAG（檢索增強生成）應用開發
規格測試：tests/spec/test_chunker.py
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    article_no: int
    content: str


def split_articles(text: str) -> list[Article]:
    """TODO：依「第N條」切塊。

    - 每條開頭是「第1條」「第 2 條」這類字樣，一條可能跨多行
    - 第一個標記之前的文字（標題、前言）捨棄
    - 沒有任何「第N條」→ 回傳空 list
    """
    raise NotImplementedError("core.chunker.split_articles 尚未實作")


def sliding_window(text: str, size: int, overlap: int) -> list[str]:
    """TODO：過長的條文再切成重疊的小段。

    - 每段最多 size 個字，下一段起點＝上一段起點 + (size - overlap)
    - 文字長度 <= size → 回傳 [text]
    - overlap >= size → raise ValueError
    """
    raise NotImplementedError("core.chunker.sliding_window 尚未實作")
