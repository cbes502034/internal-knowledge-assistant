"""檢索：向量搜尋＋BM25，以 RRF 融合。權限過濾在 SQL 內完成。

對應職缺：RAG 應用開發；PostgreSQL 的 SQL 撰寫與資料處理
（需要資料庫，沒有純函式的規格測試；完成後用 tests/ 內標記 db 的測試或手動驗證）
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import User


@dataclass
class Hit:
    chunk_id: int
    doc_title: str
    version: str
    article_no: int
    content: str
    score: float          # 向量相似度（0–1），用於拒答門檻


# 權限過濾與向量搜尋同一句完成；:參數 皆為綁定變數，不要用字串拼接
VECTOR_SEARCH_SQL = """
SELECT c.id AS chunk_id, d.title AS doc_title, d.version, c.article_no, c.content,
       1 - (c.embedding <=> :query_vec) AS score
FROM   chunks c
JOIN   documents d ON d.id = c.document_id
WHERE  d.status = 'ready'
AND   ( d.level = 'public'
     OR (d.level = 'dept'       AND d.dept_id = :dept_id)
     OR (d.level = 'restricted' AND d.dept_id = :dept_id AND :role = 'manager') )
ORDER  BY c.embedding <=> :query_vec
LIMIT  :k
"""


def vector_search(db: Session, *, query_vec: list[float], user: User, k: int) -> list[Hit]:
    """TODO：執行 VECTOR_SEARCH_SQL，回傳 Hit 清單。

    提示：db.execute(text(VECTOR_SEARCH_SQL), {...})；向量參數要轉成 pgvector 接受的格式
    """
    raise NotImplementedError("core.retriever.vector_search 尚未實作")


def keyword_search(db: Session, *, question: str, user: User, k: int) -> list[int]:
    """TODO：用 BM25Index 做關鍵字檢索，回傳 chunk_id 排名。

    要決定的事：
    - 索引何時建立、放在哪裡（啟動時載入？文件異動時更新？）
    - 索引裡只能放「這位使用者有權限」的段落，或搜尋後再過濾——哪一種安全？
    """
    raise NotImplementedError("core.retriever.keyword_search 尚未實作")


def hybrid_search(db: Session, *, question: str, user: User, k: int) -> list[Hit]:
    """TODO：混合檢索。

    1. 問題轉向量（LLMService().embed，可包一層 LRUCache）
    2. vector_search 與 keyword_search 各取前 N 筆
    3. rrf_fuse 融合兩份排名，取前 k
    4. 回傳 Hit 清單（score 保留向量相似度，供拒答門檻使用）
    """
    raise NotImplementedError("core.retriever.hybrid_search 尚未實作")
