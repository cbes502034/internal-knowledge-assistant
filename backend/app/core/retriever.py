"""
檢索層：向量檢索 + 關鍵字檢索 + 融合，且「權限過濾要寫在查詢裡」。
對應職缺：RAG 應用開發、PostgreSQL SQL 撰寫、各部門權限控管。

核心觀念：不能先檢索再用程式把沒權限的結果濾掉——LLM 看到的資料必須在查詢階段就已經過權限篩選，
否則「沒權限的內容」可能已經進了 prompt。

套件提示：pgvector（SQLAlchemy 的 Vector 欄位與 <=> 餘弦距離運算子）、sqlalchemy.text（寫原生 SQL）。
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.user import User


@dataclass
class Hit:
    """一筆檢索結果：chunk 編號、所屬文件標題、條號、內文、分數。"""
    chunk_id: int
    doc_title: str
    article_no: str | None
    content: str
    score: float


def vector_search(db: Session, query_embedding: list[float], user: User, k: int = 10) -> list[Hit]:
    """用 pgvector 的餘弦距離找最相近的 k 個 chunk，且只限 user 有權限看的文件。"""
    # TODO 1. 先決定權限規則：public 全員可看、dept 同部門可看、restricted 僅 IT 管理員（依你的資料表設計調整）
    # TODO 2. 寫 SQL：WHERE 權限條件 ORDER BY embedding <=> :query_embedding LIMIT :k
    # TODO 3. 距離越小越相似，回傳的 score 要怎麼轉換才符合「越大越好」的直覺？
    raise NotImplementedError("TODO: vector_search")


def keyword_search(db: Session, query: str, user: User, k: int = 10) -> list[Hit]:
    """關鍵字檢索：可用 bm25.py 在記憶體內算，或改用 PostgreSQL 全文檢索，兩者選一。"""
    # TODO 1. 先撈出 user 有權限的 chunk（權限過濾同樣要在查詢階段）
    # TODO 2. 用 BM25Index 算分；思考：每次查詢都重建索引合理嗎？（快取是下一步的優化題）
    raise NotImplementedError("TODO: keyword_search")


def hybrid_search(db: Session, query: str, query_embedding: list[float], user: User, k: int = 5) -> list[Hit]:
    """向量與關鍵字各取一份名次，用 rrf_fuse 融合後取前 k 筆。"""
    # TODO 1. 分別呼叫 vector_search、keyword_search
    # TODO 2. 把各自的 chunk_id 排名餵給 rrf_fuse
    # TODO 3. 依融合結果把 Hit 組回來；同一個 chunk 只能出現一次
    raise NotImplementedError("TODO: hybrid_search")
