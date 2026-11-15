"""
文件切塊（chunking）。
對應職缺：RAG 應用開發。切塊品質直接決定檢索品質，是 RAG 最容易被問「為什麼這樣切」的地方。

套件提示：re（正規表達式）、dataclasses（資料容器）。
"""

import re
from dataclasses import dataclass

# 條號標題的樣式。重點在行首錨點 ^：只有「獨立成行開頭」的「第N條」才算新的一條，
# 內文裡的「依第五條規定」不在行首，不會被誤切。
# 行首允許縮排：[^\S\r\n] 代表「除了換行以外的空白」，半形、全形空白與 tab 都算。
# 數字支援中文數字、阿拉伯數字（含全形），並支援「之一」這類附條（例如 第十條之一）。
_ARTICLE_HEADING = re.compile(
    r"^[^\S\r\n]*(第[0-9０-９一二三四五六七八九十百千零〇兩]+條(?:之[0-9０-９一二三四五六七八九十]+)?)",
    re.MULTILINE,
)


@dataclass
class Article:
    """一個「條」：article_no 是條號（例如 '第三條'），content 是該條全文。"""
    article_no: str
    content: str


def split_articles(text: str) -> list[Article]:
    """依「第N條」把法規／SOP 全文切成一條一塊；第一條之前的前言不要丟掉。"""
    text = text.strip()
    if not text:
        return []

    # TODO 1. 用 re 寫出能抓「第 + 中文數字或阿拉伯數字 + 條」的樣式（注意：條文內文中引用「依第五條」不是新的一條，要想怎麼區分）
    # 答：用 re.MULTILINE 搭配行首錨點 ^（見上方 _ARTICLE_HEADING），引用文字不在行首所以不會被切
    # TODO 2. 找出每個條號的起點位置，相鄰兩個起點之間就是一條內容
    matches = list(_ARTICLE_HEADING.finditer(text))

    # TODO 3. 沒有任何條號的文件，回傳什麼？（提示：交給 sliding_window 當後備）
    # 答：改用固定視窗切，條號欄位放「段落1、段落2…」，讓下游仍然有東西可以顯示成出處
    if not matches:
        return [
            Article(article_no=f"段落{i}", content=window)
            for i, window in enumerate(sliding_window(text), start=1)
        ]

    articles: list[Article] = []

    # 第一個條號之前的內容（文件標題、適用範圍等）是前言，仍然切成一塊保留
    preface = text[: matches[0].start()].strip()
    if preface:
        articles.append(Article(article_no="前言", content=preface))

    for i, match in enumerate(matches):
        # 這一條的終點 = 下一個條號的起點；最後一條則到文件結尾
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        articles.append(
            Article(
                article_no=match.group(1),
                content=text[match.start():end].strip(),  # 內文保留「第N條」標題本身，關鍵字檢索「第三條」才找得到
            )
        )

    return articles


def sliding_window(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """沒有條號結構的文件用的後備切法：固定長度視窗，相鄰視窗重疊 overlap 個字。"""
    # TODO 1. 步長 = size - overlap（overlap 必須小於 size，否則要拋錯，想想為什麼）
    # 答：overlap >= size 時步長 <= 0，視窗永遠不會往前走（無限迴圈或重複同一塊），所以要在一開始就擋掉
    if size <= 0:
        raise ValueError("size 必須大於 0")
    if not 0 <= overlap < size:
        raise ValueError("overlap 必須大於等於 0 且小於 size，否則視窗不會前進")

    text = text.strip()
    step = size - overlap

    # TODO 2. 從 0 開始每次前進一個步長，切出 text[i : i + size]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])

        # TODO 3. 最後一塊不足 size 也要保留，但不要產生只剩 overlap 內容的重複小尾巴
        # 答：這一塊如果已經碰到文件結尾就停；再往前走一步，新的一塊只會是上一塊尾巴的重複內容
        if start + size >= len(text):
            break
        start += step

    return chunks
