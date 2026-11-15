"""
文件切塊（chunking）。
對應職缺：RAG 應用開發。切塊品質直接決定檢索品質，是 RAG 最容易被問「為什麼這樣切」的地方。

套件提示：re（正規表達式）、dataclasses（資料容器）。
"""

from dataclasses import dataclass


@dataclass
class Article:
    """一個「條」：article_no 是條號（例如 '第三條'），content 是該條全文。"""
    article_no: str
    content: str


def split_articles(text: str) -> list[Article]:
    """依「第N條」把法規／SOP 全文切成一條一塊；第一條之前的前言不要丟掉。"""
    # TODO 1. 用 re 寫出能抓「第 + 中文數字或阿拉伯數字 + 條」的樣式（注意：條文內文中引用「依第五條」不是新的一條，要想怎麼區分）
    # TODO 2. 找出每個條號的起點位置，相鄰兩個起點之間就是一條內容
    # TODO 3. 沒有任何條號的文件，回傳什麼？（提示：交給 sliding_window 當後備）
    raise NotImplementedError("TODO: split_articles")


def sliding_window(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """沒有條號結構的文件用的後備切法：固定長度視窗，相鄰視窗重疊 overlap 個字。"""
    # TODO 1. 步長 = size - overlap（overlap 必須小於 size，否則要拋錯，想想為什麼）
    # TODO 2. 從 0 開始每次前進一個步長，切出 text[i : i + size]
    # TODO 3. 最後一塊不足 size 也要保留，但不要產生只剩 overlap 內容的重複小尾巴
    raise NotImplementedError("TODO: sliding_window")
