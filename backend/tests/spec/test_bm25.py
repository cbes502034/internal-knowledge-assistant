"""規格：app/core/bm25.py"""
import pytest

from app.core.bm25 import BM25Index, tokenize

DOCS = {
    1: "酸性與鹼性化學品須分區存放，不得混放於同一儲存櫃。",
    2: "廢溶劑暫存超過90天須聯絡合格清運廠商處理。",
    3: "發現化學品洩漏，應立即通報環安值班人員。",
}


def build() -> BM25Index:
    index = BM25Index()
    for doc_id, text in DOCS.items():
        index.add(doc_id, text)
    return index


def test_tokenize_chinese_bigrams():
    assert tokenize("廢溶劑") == ["廢溶", "溶劑"]


def test_tokenize_keeps_alnum_runs_lowercased_and_drops_punctuation():
    assert tokenize("SOP-023，超過90天") == ["sop", "023", "超過", "90", "天"]


def test_search_finds_the_relevant_document_first():
    index = build()
    assert index.search("廢溶劑放多久要處理")[0][0] == 2
    assert index.search("化學品洩漏要通知誰")[0][0] == 3


def test_scores_descend_and_zero_scores_are_excluded():
    results = build().search("化學品")
    scores = [s for _, s in results]
    assert {doc_id for doc_id, _ in results} == {1, 3}      # 文件 2 沒有「化學」「學品」
    assert scores == sorted(scores, reverse=True) and all(s > 0 for s in scores)


def test_k_limits_results():
    assert len(build().search("化學品", k=1)) == 1


def test_no_match_and_empty_index():
    assert build().search("垃圾分類") == []
    assert BM25Index().search("任何問題") == []


def test_duplicate_doc_id_rejected():
    index = build()
    with pytest.raises(ValueError):
        index.add(1, "重複加入")
