"""把文件切成檢索單位。

對應職缺：RAG（檢索增強生成）應用開發
規格測試：tests/spec/test_chunker.py

為什麼依「條」切：法規與 SOP 的最小引用單位就是條，切在條的邊界上，
找到的段落剛好是一條完整條文，出處也能精準指到「第幾條」。
沒有條號的文件（一般說明文件）改用滑動視窗。
"""
import re
from dataclasses import dataclass

WINDOW_SIZE = 500       # 滑動視窗每段最多幾個字
WINDOW_OVERLAP = 80     # 相鄰兩段重疊幾個字，避免一句話剛好被切在邊界上


@dataclass(frozen=True)
class Article:
    article_no: int
    content: str
    sub_no: int = 0     # 第 15-1 條 → article_no=15、sub_no=1


# 「第1條」「第 2 條」「第 15-1 條」，只認行首
_ARTICLE_RE = re.compile(r"^第\s*(\d+)(?:\s*-\s*(\d+))?\s*條\s*", re.MULTILINE)
# 編、章、節標題（例如「第 二 章之一 職場霸凌之防治」）不屬於任何一條，要先拿掉
_HEADING_RE = re.compile(r"^\s*第\s*[一二三四五六七八九十百零〇\d]+\s*[編章節](?:之[一二三四五六七八九十]+)?(?:\s+.*)?$",
                         re.MULTILINE)
_DELETED = {"（刪除）", "(刪除)", "刪除"}


def split_articles(text: str) -> list[Article]:
    """依「第N條」切塊。第一個條號之前的文字（標題、前言）捨棄；已刪除的條文略過。"""
    text = _HEADING_RE.sub("", text)
    markers = list(_ARTICLE_RE.finditer(text))
    articles: list[Article] = []
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        content = re.sub(r"\n\s*\n+", "\n", text[marker.end():end].strip())   # 多個空行合成一行
        if not content or content in _DELETED:
            continue
        articles.append(Article(int(marker.group(1)), content, int(marker.group(2) or 0)))
    return articles


def sliding_window(text: str, size: int, overlap: int) -> list[str]:
    """把長文字切成重疊的小段：每段最多 size 字，下一段起點＝上一段起點 + (size - overlap)。"""
    if overlap >= size:
        raise ValueError("overlap 必須小於 size，否則起點不會前進")
    if len(text) <= size:
        return [text]
    step = size - overlap
    parts: list[str] = []
    start = 0
    while True:
        parts.append(text[start:start + size])
        if start + size >= len(text):     # 這一段已經到結尾，不再產生只是前一段子集的碎片
            break
        start += step
    return parts


def split_windows(text: str) -> list[Article]:
    """沒有條號的文件：壓縮空白後用滑動視窗切段，段號從 1 開始。"""
    compact = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()
    if not compact:
        return []
    return [Article(i, part.strip()) for i, part in
            enumerate(sliding_window(compact, WINDOW_SIZE, WINDOW_OVERLAP), start=1) if part.strip()]


def parse_document(text: str) -> tuple[str, list[Article]]:
    """回傳 (切塊方式, 段落)。有條號就依條切，否則用滑動視窗。"""
    articles = split_articles(text)
    if articles:
        return "article", articles
    return "window", split_windows(text)


def make_locator(chunk_mode: str, article_no: int, sub_no: int = 0) -> str:
    """出處的顯示文字：第2條、第15-1條、第3段。"""
    if chunk_mode == "window":
        return f"第{article_no}段"
    return f"第{article_no}-{sub_no}條" if sub_no else f"第{article_no}條"
