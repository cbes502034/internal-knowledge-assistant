"""
檢索層：向量檢索 + 關鍵字檢索 + 融合，且「權限過濾要寫在查詢裡」。
對應職缺：RAG 應用開發、PostgreSQL SQL 撰寫、各部門權限控管。

核心觀念：不能先檢索再用程式把沒權限的結果濾掉——LLM 看到的資料必須在查詢階段就已經過權限篩選，
否則「沒權限的內容」可能已經進了 prompt。

套件提示：pgvector（SQLAlchemy 的 Vector 欄位與 <=> 餘弦距離運算子）、sqlalchemy.text（寫原生 SQL）。
"""

from dataclasses import dataclass, replace

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.bm25 import BM25Index
from app.core.rrf import rrf_fuse
from app.models.document import Document, DocumentChunk
from app.models.user import User, UserRole

# 融合前，每一路先各撈這麼多筆候選；太少會讓融合沒得選，太多只是白算
RECALL_K = 20


@dataclass
class Hit:
    """一筆檢索結果：chunk 編號、所屬文件標題、條號、內文、分數。"""
    chunk_id: int
    doc_title: str
    article_no: str | None
    content: str
    score: float  # 排名用的分數：單路檢索時是該路的分數，hybrid_search 之後是 RRF 分數
    similarity: float | None = None  # 向量餘弦相似度（0~1，越大越像）；沒出現在向量結果中則為 None


def _visible_to(user: User):
    """這位使用者「看得到哪些文件」的 SQL 條件；向量與關鍵字兩條路共用，權限規則只有這一份。"""
    # TODO 1. 先決定權限規則：public 全員可看、dept 同部門可看、restricted 僅 IT 管理員（依你的資料表設計調整）
    allowed = [
        Document.level == "public",
        and_(Document.level == "dept", Document.dept_id == user.dept_id),
    ]
    if user.role == UserRole.IT_ADMIN.value:
        allowed.append(Document.level == "restricted")

    # 只檢索處理完成（ready）的文件；pending / failed / deprecated 一律不讓模型看到
    return and_(Document.status == "ready", or_(*allowed))


def vector_search(db: Session, query_embedding: list[float], user: User, k: int = 10) -> list[Hit]:
    """用 pgvector 的餘弦距離找最相近的 k 個 chunk，且只限 user 有權限看的文件。"""
    # TODO 2. 寫 SQL：WHERE 權限條件 ORDER BY embedding <=> :query_embedding LIMIT :k
    # cosine_distance 對應 SQL 的 <=> 運算子；只挑需要的欄位，不把 1024 維向量整個撈回來
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            DocumentChunk.id,
            Document.title,
            DocumentChunk.article_no,
            DocumentChunk.content,
            distance.label("distance"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(_visible_to(user))
        .order_by(distance, DocumentChunk.id)  # 距離相同時用編號排，結果才可重現
        .limit(k)
    )

    # TODO 3. 距離越小越相似，回傳的 score 要怎麼轉換才符合「越大越好」的直覺？
    # 答：相似度 = 1 - 餘弦距離
    return [
        Hit(
            chunk_id=row.id,
            doc_title=row.title,
            article_no=row.article_no,
            content=row.content,
            score=1.0 - row.distance,
            similarity=1.0 - row.distance,
        )
        for row in db.execute(stmt)
    ]


def keyword_search(db: Session, query: str, user: User, k: int = 10) -> list[Hit]:
    """關鍵字檢索：可用 bm25.py 在記憶體內算，或改用 PostgreSQL 全文檢索，兩者選一。"""
    # TODO 1. 先撈出 user 有權限的 chunk（權限過濾同樣要在查詢階段）
    stmt = (
        select(DocumentChunk.id, Document.title, DocumentChunk.article_no, DocumentChunk.content)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(_visible_to(user))
        .order_by(DocumentChunk.id)  # 固定順序：BM25 的文件編號是這個清單的位置，順序變了結果會跟著變
    )
    rows = db.execute(stmt).all()
    if not rows:
        return []

    # TODO 2. 用 BM25Index 算分；思考：每次查詢都重建索引合理嗎？（快取是下一步的優化題）
    # 答：不合理，但語料小的時候夠用；每次查詢都重新讀取並建索引，成本會隨文件量線性增加，之後可依權限範圍快取索引。
    # 索引文字帶上文件標題：查「廢棄物處理 第三條」這類問法時，標題也要能命中
    index = BM25Index([f"{row.title} {row.content}" for row in rows])

    return [
        Hit(
            chunk_id=rows[position].id,
            doc_title=rows[position].title,
            article_no=rows[position].article_no,
            content=rows[position].content,
            score=score,
        )
        for position, score in index.search(query, k)
    ]


def hybrid_search(db: Session, query: str, query_embedding: list[float], user: User, k: int = 5) -> list[Hit]:
    """向量與關鍵字各取一份名次，用 rrf_fuse 融合後取前 k 筆。"""
    # TODO 1. 分別呼叫 vector_search、keyword_search
    pool = max(RECALL_K, k)
    vector_hits = vector_search(db, query_embedding, user, pool)
    keyword_hits = keyword_search(db, query, user, pool)

    # TODO 2. 把各自的 chunk_id 排名餵給 rrf_fuse
    fused = rrf_fuse(
        [
            [hit.chunk_id for hit in vector_hits],
            [hit.chunk_id for hit in keyword_hits],
        ]
    )

    # TODO 3. 依融合結果把 Hit 組回來；同一個 chunk 只能出現一次
    # 兩路都找到的 chunk 優先用向量那筆：它帶有 similarity，rag.py 的拒答判斷要用
    by_id = {hit.chunk_id: hit for hit in keyword_hits}
    by_id.update({hit.chunk_id: hit for hit in vector_hits})

    return [replace(by_id[chunk_id], score=rrf_score) for chunk_id, rrf_score in fused[:k]]
