"""檢索：向量搜尋＋BM25，以 RRF 融合。權限過濾在 SQL 內完成。

對應職缺：RAG 應用開發；PostgreSQL 的 SQL 撰寫與資料處理

安全原則：使用者沒有權限的段落，從資料庫出來時就已經被排除，
不會進到排名、不會進到提示詞，更不靠「叫模型不要說」來保護。
"""
import re
import threading
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.bm25 import BM25Index
from app.core.chunker import make_locator
from app.core.llm_service import get_llm
from app.core.lru_cache import LRUCache
from app.core.rrf import rrf_fuse

SEARCH_MODES = ("hybrid", "vector", "keyword")


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    doc_title: str
    version: str
    article_no: int
    sub_no: int
    locator: str          # 第2條、第15-1條、第3段
    content: str
    score: float          # 向量相似度（0–1），用於拒答門檻


# 權限條件：三處共用（向量檢索、關鍵字的可見範圍、依編號補資料）。:參數 皆為綁定變數，不用字串拼接。
PERMISSION_SQL = """
    d.status = 'ready'
AND ( d.level = 'public'
   OR (d.level = 'dept'       AND d.dept_id = :dept_id)
   OR (d.level = 'restricted' AND d.dept_id = :dept_id AND :role = 'manager') )"""

_SELECT_HITS = """
SELECT c.id AS chunk_id, d.id AS document_id, d.title AS doc_title, d.version, d.chunk_mode,
       c.article_no, c.sub_no, c.content,
       1 - (c.embedding <=> CAST(:query_vec AS vector)) AS score
FROM   chunks c
JOIN   documents d ON d.id = c.document_id"""

VECTOR_SEARCH_SQL = _SELECT_HITS + """
WHERE  c.embedding IS NOT NULL AND""" + PERMISSION_SQL + """
ORDER  BY c.embedding <=> CAST(:query_vec AS vector)
LIMIT  :k"""

FETCH_BY_IDS_SQL = _SELECT_HITS + """
WHERE  c.id = ANY(:ids) AND""" + PERMISSION_SQL

VISIBLE_IDS_SQL = """
SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE""" + PERMISSION_SQL

# 關鍵字索引的「版本戳記」：可檢索段落的數量、最大編號、編號總和。
# 文件新增、重新處理（段落編號會變）、作廢都會改變它，多個 worker 各自比對也能發現變化。
_INDEX_STAMP_SQL = """
SELECT count(*), coalesce(max(c.id), 0), coalesce(sum(c.id), 0)
FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.status = 'ready'"""

_INDEX_ROWS_SQL = """
SELECT c.id, d.title, c.content
FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.status = 'ready'"""


def to_pgvector(vec) -> str:
    """Python 的 list 轉成 pgvector 接受的文字格式 '[0.1,0.2,...]'，再在 SQL 中 CAST 成 vector。"""
    return "[" + ",".join(f"{float(x):.7g}" for x in vec) + "]"


def _params(user, **extra) -> dict:
    return {"dept_id": user.dept_id, "role": user.role, **extra}


def _row_to_hit(row) -> Hit:
    return Hit(chunk_id=row.chunk_id, document_id=row.document_id, doc_title=row.doc_title, version=row.version,
               article_no=row.article_no, sub_no=row.sub_no,
               locator=make_locator(row.chunk_mode, row.article_no, row.sub_no),
               content=row.content, score=float(row.score))


# ---------- 問題向量：LRU 快取 ----------
_embed_cache = LRUCache(get_settings().embed_cache_size)
_embed_lock = threading.Lock()


def embed_query(question: str) -> list[float]:
    """問題轉向量；同一個問題（同一個模型）直接用快取。"""
    llm = get_llm()
    key = (llm.embed_model, question.strip())
    with _embed_lock:
        cached = _embed_cache.get(key)
    if cached is not None:
        return cached
    vector = llm.embed(question)
    with _embed_lock:
        _embed_cache.put(key, vector)
    return vector


# ---------- 向量檢索 ----------
def vector_search(db: Session, *, query_vec: list[float], user, k: int) -> list[Hit]:
    rows = db.execute(text(VECTOR_SEARCH_SQL), _params(user, query_vec=to_pgvector(query_vec), k=k))
    return [_row_to_hit(row) for row in rows]


# ---------- 關鍵字檢索 ----------
class _KeywordIndexCache:
    """BM25 索引放在記憶體；資料有變化（戳記不同）才重建。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._index: BM25Index | None = None

    def get(self, db: Session) -> BM25Index:
        stamp = tuple(db.execute(text(_INDEX_STAMP_SQL)).one())
        with self._lock:
            if stamp != self._stamp or self._index is None:
                index = BM25Index()
                for chunk_id, title, content in db.execute(text(_INDEX_ROWS_SQL)):
                    index.add(chunk_id, f"{title}\n{content}")   # 標題也算進去：問題提到法規名稱時能對上
                self._index, self._stamp = index, stamp
            return self._index

    def clear(self) -> None:
        with self._lock:
            self._index, self._stamp = None, None


_keyword_cache = _KeywordIndexCache()


def keyword_search(db: Session, *, question: str, user, k: int) -> list[int]:
    """BM25 排名（段落編號）。索引包含所有可檢索段落，計分時只看這位使用者看得到的。

    權限仍由同一段 SQL 條件決定（VISIBLE_IDS_SQL），而且在計分「之前」過濾，
    所以沒有權限的段落不會占用名額，也不會出現在結果中。
    """
    index = _keyword_cache.get(db)
    visible = {row[0] for row in db.execute(text(VISIBLE_IDS_SQL), _params(user))}
    return [chunk_id for chunk_id, _ in index.search(question, k=k, allowed=visible)]


# ---------- 混合檢索 ----------
def hybrid_search(db: Session, *, question: str, user, k: int, mode: str | None = None,
                  keyword_weight: float | None = None) -> list[Hit]:
    """取前 k 個段落。mode：hybrid（加權 RRF 融合）、vector、keyword；預設看設定 SEARCH_MODE。

    三種模式都會算問題向量：拒答門檻用的是向量相似度。
    """
    settings = get_settings()
    mode = mode or settings.search_mode
    if mode not in SEARCH_MODES:
        raise ValueError(f"未知的檢索方式：{mode}")
    weight = settings.keyword_weight if keyword_weight is None else keyword_weight
    candidates = max(k, settings.candidates)
    query_vec = embed_query(question)

    vector_hits = vector_search(db, query_vec=query_vec, user=user, k=candidates) if mode != "keyword" else []
    keyword_ids = keyword_search(db, question=question, user=user, k=candidates) if mode != "vector" else []

    if mode == "vector":
        ranked = [hit.chunk_id for hit in vector_hits]
    elif mode == "keyword":
        ranked = keyword_ids
    else:
        fused = rrf_fuse([[hit.chunk_id for hit in vector_hits], keyword_ids], weights=[1.0, weight])
        ranked = [chunk_id for chunk_id, _ in fused]
    top_ids = ranked[:k]

    # 只出現在關鍵字排名的段落，補查內容與向量相似度（同樣套用權限條件，雙重保險）
    by_id = {hit.chunk_id: hit for hit in vector_hits}
    missing = [chunk_id for chunk_id in top_ids if chunk_id not in by_id]
    if missing:
        rows = db.execute(text(FETCH_BY_IDS_SQL), _params(user, ids=missing, query_vec=to_pgvector(query_vec)))
        by_id.update({hit.chunk_id: hit for hit in map(_row_to_hit, rows)})
    return [by_id[chunk_id] for chunk_id in top_ids if chunk_id in by_id]


# ---------- 拒答判斷 ----------
# 英數代號、分機、料號這類精確字詞：問題長度短時向量相似度偏低（例如「ECN是什麼」只有 0.45），
# 但字面完全對上就是很強的證據。3 個字元以上才算，避免 Wi、Fi 這種片段誤判。
_EXACT_TERM_RE = re.compile(r"[a-z0-9]{3,}")


def exact_term_match(question: str, hits: list[Hit]) -> bool:
    terms = set(_EXACT_TERM_RE.findall(unicodedata.normalize("NFKC", question).lower()))
    if not terms:
        return False
    contents = [unicodedata.normalize("NFKC", hit.content).lower() for hit in hits]
    return any(term in content for term in terms for content in contents)


def should_refuse(question: str, hits: list[Hit], threshold: float) -> bool:
    """沒有段落，或最高向量相似度低於門檻且沒有精確字詞相符 → 拒答（不呼叫模型）。

    問答與評測共用這個函式，評測量到的拒答行為就是實際上線的行為。
    """
    if not hits:
        return True
    if max(hit.score for hit in hits) >= threshold:
        return False
    return not exact_term_match(question, hits)


# ---------- 快取管理 ----------
def clear_query_cache() -> None:
    """清除問題向量快取（評測量耗時前使用，避免後面的批次因為快取而顯得特別快）。"""
    global _embed_cache
    with _embed_lock:
        _embed_cache = LRUCache(get_settings().embed_cache_size)


def warm_up(db: Session) -> None:
    """先建好關鍵字索引，讓第一個請求不必等。"""
    _keyword_cache.get(db)


def clear_caches() -> None:
    """清除關鍵字索引與問題向量快取（測試或換模型時使用）。"""
    _keyword_cache.clear()
    clear_query_cache()
