"""規格：app/core/chunker.py"""
import pytest

from app.core.chunker import Article, sliding_window, split_articles

SOP = """廢棄物處理SOP（模擬資料）

第1條 廢溶劑須以專用容器收集，
容器須標示廢棄物代碼與產生日期。
第 2 條 廢溶劑暫存超過90天須聯絡合格清運廠商處理。
第3條 清運時須填寫清運聯單，並保存三年。
"""


def test_split_by_article():
    articles = split_articles(SOP)
    assert [a.article_no for a in articles] == [1, 2, 3]
    assert articles[1] == Article(2, "廢溶劑暫存超過90天須聯絡合格清運廠商處理。")


def test_article_may_span_lines_and_preamble_is_dropped():
    first = split_articles(SOP)[0]
    assert "專用容器" in first.content and "產生日期" in first.content
    assert "模擬資料" not in first.content


def test_no_article_markers_returns_empty():
    assert split_articles("這份文件沒有條號。") == []


def test_sliding_window_short_text_unchanged():
    assert sliding_window("短文字", size=10, overlap=2) == ["短文字"]


def test_sliding_window_overlaps():
    parts = sliding_window("0123456789", size=4, overlap=1)
    assert parts == ["0123", "3456", "6789"]


def test_sliding_window_rejects_bad_overlap():
    with pytest.raises(ValueError):
        sliding_window("0123456789", size=4, overlap=4)
