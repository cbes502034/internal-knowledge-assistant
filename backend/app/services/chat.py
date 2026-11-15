"""
【檔案用途】對話服務：把 RAG 的回答存成訊息與出處，並在讀取時組出前端要的格式。
對應職缺：後端 API 開發、RAG 應用落地（紀錄、出處、回饋）。

RAG 本身（檢索、拒答、生成）在 services/rag.py 的 answer_question，這裡只負責「接上資料庫」：
  ask()          提問：存問題 → 呼叫 RAG → 存回答與出處
  to_responses() 讀取：訊息轉成回應格式，並依目前權限補上出處原文

被誰呼叫：routers/conversations.py。
"""

import time  # perf_counter：量測回答花了多少毫秒
from collections.abc import Sequence  # 型別註記：任何「可依序讀取」的集合（list、tuple、查詢結果都可以）

from sqlalchemy import select  # 組 SELECT 查詢
from sqlalchemy.orm import Session  # 型別註記：資料庫工作階段

# _visible_to：「這位使用者看得到哪些文件」的 SQL 條件。
# 讀取出處原文時要和檢索用「同一套」權限規則，所以直接共用，不重寫一份
from app.core.retriever import _visible_to
from app.models.conversation import Conversation, Message, MessageCitation  # 對話三張表
from app.models.document import Document, DocumentChunk  # 查出處的版本與原文
from app.models.user import User  # 型別註記：目前登入者
from app.schemas.chat import MessageResponse  # 回應給前端的訊息格式
from app.services.rag import REFUSE_TEXT, answer_question  # RAG 主流程與拒答文字（模型系列）

TITLE_LENGTH = 28  # 對話標題取第一個問題的前 28 字，和前端一致


def ask(db: Session, user: User, conversation: Conversation, content: str) -> Message:
    """存提問 → 呼叫 RAG → 存回答與出處，回傳助理的那則訊息。"""
    # ── 1. 存提問（必要時順便設定對話標題）──
    db.add(Message(conversation_id=conversation.id, role="user", content=content))
    if conversation.title is None:
        conversation.title = content[:TITLE_LENGTH]
    # 先 commit 提問：模型要跑好幾秒到幾十秒，這段期間就算出錯，問題本身也已經留下紀錄
    db.commit()

    # ── 2. 呼叫 RAG 並量測耗時 ──
    started = time.perf_counter()  # perf_counter 是專門量時間差的高精度計時器
    result = answer_question(db, user, content)
    latency_ms = int((time.perf_counter() - started) * 1000)

    # ── 3. 查出處的文件版本 ──
    hits = result["citations"]  # 實際放進 prompt 的檢索結果（Hit 物件清單）
    # Hit 沒有版本欄位，另外查一次（一次查完所有出處，不要每個出處各查一次）
    versions = dict(  # 查詢結果是 (chunk_id, version) 的清單，轉成 {chunk_id: version}
        db.execute(
            select(DocumentChunk.id, Document.version)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_([hit.chunk_id for hit in hits]))
        ).all()
    ) if hits else {}  # 拒答時沒有出處，不用查

    # ── 4. 組出回答訊息與出處快照 ──
    answer = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result["answer"],
        refused=result["answer"] == REFUSE_TEXT,  # 回答等於固定拒答文字，就是拒答
        latency_ms=latency_ms,
        citations=[  # 透過 relationship 直接掛上出處，commit 時會一起寫入
            MessageCitation(
                chunk_id=hit.chunk_id,
                rank=rank,
                doc_title=hit.doc_title,
                version=versions.get(hit.chunk_id),
                article_no=hit.article_no,
                score=hit.similarity,  # 用向量相似度（有絕對意義），不用只看名次的 RRF 分數
            )
            for rank, hit in enumerate(hits, start=1)  # 排名從 1 開始
        ],
    )

    # ── 5. 寫入並回傳 ──
    db.add(answer)
    db.commit()
    db.refresh(answer)  # 取得資料庫產生的 id、created_at
    return answer


def to_responses(db: Session, user: User, messages: Sequence[Message]) -> list[MessageResponse]:
    """
    把訊息轉成回應格式，並補上出處的原文片段。

    原文片段「每次讀取時」依目前的權限重新檢查，而不是存在出處表裡：
    使用者可能已經換部門、文件可能已經改成限閱或作廢，當初看得到不代表現在還看得到。
    """
    # ── 1. 收集所有出處用到的 chunk 編號（集合推導式，自動去重）──
    chunk_ids = {c.chunk_id for m in messages for c in m.citations if c.chunk_id is not None}

    # ── 2. 一次查出「目前仍看得到」的原文：{chunk_id: 內文} ──
    previews: dict[int, str] = {}
    if chunk_ids:
        previews = dict(
            db.execute(
                select(DocumentChunk.id, DocumentChunk.content)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(DocumentChunk.id.in_(chunk_ids), _visible_to(user))  # 和檢索用同一套權限條件
            ).all()
        )

    # ── 3. 逐則轉成回應格式，把原文填進對應的出處 ──
    responses = []
    for message in messages:
        # model_validate：從 ORM 物件讀屬性建立 Pydantic 物件（需要 from_attributes=True）
        response = MessageResponse.model_validate(message)
        # 回應的出處與資料庫的出處順序相同，用 zip 一一配對
        for citation_response, citation in zip(response.citations, message.citations):
            citation_response.preview = previews.get(citation.chunk_id)  # 沒權限或已刪除 → None
        responses.append(response)
    return responses
