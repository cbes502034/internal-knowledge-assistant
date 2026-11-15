"""不需要資料庫的測試：切塊、BM25、RRF、LLM 服務（用假的 Ollama 伺服器模擬各種失敗）、問答的輔助函式。"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from app.core import llm_service
from app.core.bm25 import BM25Index, tokenize
from app.core.chunker import sliding_window, split_articles
from app.core.config import settings
from app.core.llm_service import LLMService, LLMUnavailableError
from app.core.retriever import Hit
from app.core.rrf import rrf_fuse
from app.models.document import EMBEDDING_DIM
from app.services.rag import build_context, fit_hits


# ───────────────────────── chunker ─────────────────────────

SOP = """化學品管理SOP
所屬部門：ops

第1條 化學品進廠前須確認 SDS。
第2條 儲存量不得超過上限，超過者依第1條規定通報。
第三條之一 另有規定者從其規定。
"""


def test_split_articles_headings_and_preface():
    articles = split_articles(SOP)
    assert [a.article_no for a in articles] == ["前言", "第1條", "第2條", "第三條之一"]
    assert "所屬部門" in articles[0].content


def test_split_articles_body_reference_is_not_a_new_article():
    # 第2條內文裡的「依第1條規定」不在行首，不能被當成新的一條
    article_2 = split_articles(SOP)[2]
    assert article_2.content.startswith("第2條")
    assert "依第1條規定通報" in article_2.content


def test_split_articles_no_preface_when_text_starts_with_heading():
    articles = split_articles("第1條 甲\n第2條 乙")
    assert [a.article_no for a in articles] == ["第1條", "第2條"]


def test_split_articles_fullwidth_digits_and_indent():
    articles = split_articles("  第１條 甲\n　第２條 乙")
    assert [a.article_no for a in articles] == ["第１條", "第２條"]


def test_split_articles_falls_back_to_windows_when_no_headings():
    text = "甲" * 1200
    articles = split_articles(text)
    assert [a.article_no for a in articles] == [f"段落{i}" for i in range(1, len(sliding_window(text)) + 1)]
    assert len(articles) == 3  # 500 字一塊、重疊 50：0-500、450-950、900-1200


@pytest.mark.parametrize("text", ["", "   \n  "])
def test_split_articles_empty(text):
    assert split_articles(text) == []


def test_sliding_window_exact_output():
    assert sliding_window("abcdefghij", size=4, overlap=1) == ["abcd", "defg", "ghij"]


def test_sliding_window_has_no_overlap_only_tail():
    # 最後一塊要帶著新內容（ghi），不能只剩上一塊的重疊字（g）
    assert sliding_window("abcdefghi", size=4, overlap=1) == ["abcd", "defg", "ghi"]


def test_sliding_window_zero_overlap_and_short_text():
    assert sliding_window("abcdef", size=3, overlap=0) == ["abc", "def"]
    assert sliding_window("abc", size=10, overlap=2) == ["abc"]
    assert sliding_window("", size=10, overlap=2) == []


@pytest.mark.parametrize("size,overlap", [(0, 0), (-1, 0), (5, 5), (5, 6), (5, -1)])
def test_sliding_window_rejects_bad_parameters(size, overlap):
    with pytest.raises(ValueError):
        sliding_window("abcdefghij", size=size, overlap=overlap)


@pytest.mark.parametrize("size,overlap", [(7, 2), (10, 0), (50, 10)])
def test_sliding_window_covers_whole_text(size, overlap):
    text = "".join(chr(0x4E00 + i % 500) for i in range(333))
    chunks = sliding_window(text, size=size, overlap=overlap)
    rebuilt = chunks[0] + "".join(c[overlap:] for c in chunks[1:])
    assert rebuilt == text


# ───────────────────────── bm25 ─────────────────────────

def test_tokenize_chinese_bigram():
    assert tokenize("廢溶劑") == ["廢溶", "溶劑"]


def test_tokenize_single_chinese_char_is_kept():
    assert tokenize("廢") == ["廢"]


def test_tokenize_alnum_runs_and_punctuation():
    assert tokenize("SOP-OPS-004！") == ["sop", "ops", "004"]
    assert tokenize("第3條 廢溶劑") == ["第", "3", "條", "廢溶", "溶劑"]


def test_tokenize_fullwidth_and_empty():
    assert tokenize("ＳＯＰ１") == ["sop1"]
    assert tokenize("") == []
    assert tokenize("，。！ ") == []


DOCS = ["廢溶劑暫存期限不得超過九十天", "廢溶劑容器應標示內容物與日期", "出差住宿費每晚上限三千元"]


def test_bm25_ranks_relevant_first_and_excludes_unmatched():
    results = BM25Index(DOCS).search("廢溶劑暫存期限")
    assert results[0][0] == 0
    assert [doc_id for doc_id, _ in results] == [0, 1]  # 第 2 份完全不相關，不該出現
    assert all(score > 0 for _, score in results)
    assert results[0][1] > results[1][1]


def test_bm25_top_k_and_degenerate_inputs():
    index = BM25Index(DOCS)
    assert len(index.search("廢溶劑", k=1)) == 1
    assert index.search("廢溶劑", k=0) == []
    assert index.search("完全無關xyz") == []
    assert BM25Index([]).search("a") == []


def test_bm25_rare_terms_have_higher_idf():
    index = BM25Index(DOCS)
    assert index.idf["暫存"] > index.idf["廢溶"]  # 「暫存」只在 1 份文件出現，「廢溶」在 2 份


def test_bm25_penalises_long_documents():
    docs = ["廢溶劑", "廢溶劑" + "無關內容" * 20]
    results = BM25Index(docs).search("廢溶劑")
    assert [doc_id for doc_id, _ in results] == [0, 1]
    assert results[0][1] > results[1][1]


def test_bm25_ties_are_ordered_by_doc_id():
    results = BM25Index(["廢溶劑", "廢溶劑", "廢溶劑"]).search("廢溶劑")
    assert [doc_id for doc_id, _ in results] == [0, 1, 2]


def test_bm25_score_matches_hand_calculation():
    # N=3, avgdl=2, df(cat)=2 → idf=ln(1.6)
    # d0: tf=1,len=2 → 0.470004；d1: tf=2,len=3 → 0.578466（手算）
    results = dict(BM25Index(["cat dog", "cat cat bird", "fish"]).search("cat"))
    assert results[0] == pytest.approx(0.470004, abs=1e-5)
    assert results[1] == pytest.approx(0.578466, abs=1e-5)


# ───────────────────────── rrf ─────────────────────────

def test_rrf_scores_and_order():
    fused = dict(rrf_fuse([[1, 2, 3], [3, 2, 4]]))
    assert fused[1] == pytest.approx(1 / 61)
    assert fused[2] == pytest.approx(1 / 62 + 1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[4] == pytest.approx(1 / 63)
    assert [doc_id for doc_id, _ in rrf_fuse([[1, 2, 3], [3, 2, 4]])] == [3, 2, 1, 4]


def test_rrf_document_in_both_lists_beats_single_list_winner():
    # 兩份清單的第一名都不一樣，但 9 在兩份都排前面，應該贏
    assert rrf_fuse([[1, 9], [2, 9]])[0][0] == 9


def test_rrf_ties_keep_first_seen_order():
    assert [doc_id for doc_id, _ in rrf_fuse([[1, 2], [2, 1]])] == [1, 2]


def test_rrf_duplicates_in_one_list_count_once():
    assert dict(rrf_fuse([[7, 7, 7]]))[7] == pytest.approx(1 / 61)


def test_rrf_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


# ─────────────────── rag 輔助函式（不需資料庫）───────────────────

def _hit(content="內容", article_no="第1條", title="文件"):
    return Hit(chunk_id=1, doc_title=title, article_no=article_no, content=content, score=0.0)


def test_build_context_format():
    context = build_context([_hit("甲", "第2條", "廢棄物處理SOP"), _hit("乙", None, "手冊")])
    assert context == "[廢棄物處理SOP 第2條]\n甲\n\n[手冊]\n乙"


def test_fit_hits_respects_budget_but_keeps_first():
    hits = [_hit("甲" * 1000) for _ in range(4)]
    assert len(fit_hits(hits, max_chars=2500)) == 2
    assert len(fit_hits(hits, max_chars=10)) == 1  # 第一筆單獨就超標，也要保留
    assert fit_hits([], max_chars=10) == []


# ───────────────────── llm_service（假的 Ollama）─────────────────────

class FakeOllama:
    """腳本化的假 Ollama：依序回傳 script 裡的 (狀態碼, 內容, 延遲秒數)，用完後重複最後一筆。"""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append((self.path, json.loads(self.rfile.read(length) or b"{}")))
                status, payload, delay = outer.script[min(len(outer.requests), len(outer.script)) - 1]
                if delay:
                    threading.Event().wait(delay)
                data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionError):
                    pass  # 客戶端已經逾時離開

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_ollama():
    servers = []

    def start(script):
        server = FakeOllama(script)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


@pytest.fixture
def sleeps(monkeypatch):
    """攔截重試之間的等待：不真的睡，只記錄每次打算睡多久。"""
    recorded = []
    monkeypatch.setattr(llm_service, "time", SimpleNamespace(sleep=recorded.append))
    return recorded


def make_service(url, **kwargs):
    return LLMService(url, "embed-m", "chat-m", **kwargs)


def test_embed_returns_first_vector_and_sends_expected_payload(fake_ollama):
    server = fake_ollama([(200, {"embeddings": [[0.1, 0.2, 0.3]]}, 0)])
    assert make_service(server.url + "/").embed("你好") == [0.1, 0.2, 0.3]  # 結尾斜線不能讓網址變成 //api
    assert server.requests == [("/api/embed", {"model": "embed-m", "input": "你好"})]


def test_generate_payload_and_strip(fake_ollama):
    server = fake_ollama([(200, {"response": "  答案  \n"}, 0)])
    assert make_service(server.url).generate("問題") == "答案"
    path, body = server.requests[0]
    assert path == "/api/generate"
    assert body["model"] == "chat-m" and body["prompt"] == "問題"
    assert body["stream"] is False
    assert body["options"]["temperature"] <= 0.2


def test_retries_5xx_with_exponential_backoff_then_succeeds(fake_ollama, sleeps):
    server = fake_ollama([(500, {}, 0), (503, {}, 0), (200, {"response": "ok"}, 0)])
    assert make_service(server.url).generate("q") == "ok"
    assert len(server.requests) == 3
    assert sleeps == [1, 2]


def test_gives_up_after_max_retries(fake_ollama, sleeps):
    server = fake_ollama([(500, {}, 0)])
    with pytest.raises(LLMUnavailableError):
        make_service(server.url, max_retries=3).generate("q")
    assert len(server.requests) == 3
    assert sleeps == [1, 2]  # 最後一次失敗後不再等待


def test_4xx_is_not_retried(fake_ollama, sleeps):
    server = fake_ollama([(404, {"error": "model not found"}, 0)])
    with pytest.raises(LLMUnavailableError, match="404"):
        make_service(server.url).generate("q")
    assert len(server.requests) == 1
    assert sleeps == []


def test_connection_refused_is_retried(sleeps):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # 取得一個「現在沒人在聽」的埠
    with pytest.raises(LLMUnavailableError):
        make_service(f"http://127.0.0.1:{port}").embed("q")
    assert sleeps == [1, 2]


def test_timeout_is_retried(fake_ollama, sleeps):
    server = fake_ollama([(200, {"response": "太慢了"}, 1.0)])
    with pytest.raises(LLMUnavailableError):
        make_service(server.url, timeout=0.2, max_retries=2).generate("q")
    assert len(server.requests) == 2
    assert sleeps == [1]


def test_invalid_json_and_missing_fields_raise(fake_ollama, sleeps):
    with pytest.raises(LLMUnavailableError, match="JSON"):
        make_service(fake_ollama([(200, "這不是 JSON", 0)]).url).generate("q")
    with pytest.raises(LLMUnavailableError, match="embeddings"):
        make_service(fake_ollama([(200, {"foo": 1}, 0)]).url).embed("q")
    with pytest.raises(LLMUnavailableError, match="response"):
        make_service(fake_ollama([(200, {"foo": 1}, 0)]).url).generate("q")


# ───────────────────── 真的 Ollama（沒開就略過）─────────────────────

@pytest.fixture(scope="module")
def real_llm():
    try:
        httpx.get(settings.ollama_base_url + "/api/tags", timeout=3).raise_for_status()
    except Exception:
        pytest.skip("Ollama 沒有在執行")
    return LLMService(settings.ollama_base_url, settings.embed_model, settings.chat_model, timeout=settings.llm_timeout)


@pytest.mark.ollama
def test_real_embedding_dimension_matches_database_column(real_llm):
    # 嵌入模型的維度與資料庫 vector 欄位不一致，是 RAG 最常見的入庫錯誤
    assert len(real_llm.embed("廢溶劑暫存期限")) == EMBEDDING_DIM


@pytest.mark.ollama
def test_real_generate_returns_text(real_llm):
    assert real_llm.generate("請只回答一個字：好").strip()
