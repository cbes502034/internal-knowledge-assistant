"""拒答規則、加權 RRF、條號與出處文字（不需要資料庫與模型）。"""
import pytest

from app.core.chunker import Article, make_locator, parse_document, split_articles
from app.core.retriever import Hit, exact_term_match, should_refuse
from app.core.rrf import rrf_fuse
from app.services.rag import is_refusal, select_citations, to_traditional


def test_simplified_characters_are_fixed_but_source_wording_is_kept():
    context = "雇主應於八小時內通報。廢溶劑暫存超過90天。"
    assert to_traditional("废溶劑超過90天 [1]", context) == "廢溶劑超過90天 [1]"
    assert to_traditional("雇主應於八小時內通報 [1]", context) == "雇主應於八小時內通報 [1]"


def hit(content: str, score: float) -> Hit:
    return Hit(chunk_id=1, document_id=1, doc_title="文件", version="v1", article_no=1, sub_no=0,
               locator="第1條", content=content, score=score)


def test_high_similarity_is_answered():
    assert should_refuse("廢溶劑放多久", [hit("廢溶劑暫存超過90天", 0.8)], 0.56) is False


def test_low_similarity_is_refused():
    assert should_refuse("員工餐廳幾點開", [hit("廢溶劑暫存超過90天", 0.4)], 0.56) is True
    assert should_refuse("任何問題", [], 0.56) is True


def test_exact_code_rescues_low_similarity():
    assert should_refuse("ECN是什麼", [hit("提出工程變更通知（ECN）", 0.45)], 0.56) is False
    assert exact_term_match("分機1199是誰", [hit("通報環安值班人員（分機1199）", 0.4)]) is True


def test_short_ascii_fragments_are_not_evidence():
    assert exact_term_match("訪客Wi-Fi密碼", [hit("Wi Fi 設定", 0.4)]) is False


def test_weighted_rrf_lets_the_first_ranking_dominate():
    fused = dict(rrf_fuse([[1, 2], [2, 1]], weights=[1.0, 0.3]))
    assert fused[1] > fused[2]
    with pytest.raises(ValueError):
        rrf_fuse([[1]], weights=[1.0, 0.5])


def test_law_text_with_chapters_sub_articles_and_deleted_articles():
    text = "第 一 章 總則\n第 1 條\n甲。\n第 二 章之一 職場霸凌之防治\n第 22-1 條\n乙。\n第 23 條\n（刪除）\n"
    assert split_articles(text) == [Article(1, "甲。"), Article(22, "乙。", 1)]


def test_document_without_articles_falls_back_to_windows():
    mode, parts = parse_document("沒有條號的說明。" * 120)
    assert mode == "window" and len(parts) >= 2 and parts[0].article_no == 1


def test_locator_text():
    assert make_locator("article", 15, 1) == "第15-1條"
    assert make_locator("article", 2) == "第2條"
    assert make_locator("window", 3) == "第3段"


def test_citations_follow_the_numbers_in_the_answer():
    hits = [hit("甲", 0.9), hit("乙", 0.8), hit("丙", 0.7)]
    assert [rank for rank, _ in select_citations("依規定 [3]，另見 [1]。", hits)] == [1, 3]
    assert [rank for rank, _ in select_citations("沒有標編號", hits)] == [1, 2, 3]
    assert [rank for rank, _ in select_citations("亂標 [9]", hits)] == [1, 2, 3]


def test_refusal_detection_only_matches_the_refusal_sentence():
    assert is_refusal("找不到相關規定。") is True
    assert is_refusal("當助理回答「找不到相關規定」時，代表沒有依據 [1]。") is False
