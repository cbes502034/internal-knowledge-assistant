"""
對話服務：把 RAG 的回答存成訊息與出處，並在讀取時組出前端要的格式。
對應職缺：後端 API 開發、RAG 應用落地（紀錄、出處、回饋）。

RAG 本身（檢索、拒答、生成）在 services/rag.py 的 answer_question，這裡只負責「接上資料庫」。
"""

import time
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.retriever import _visible_to
from app.models.conversation import Conversation, Message, MessageCitation
from app.models.document import Document, DocumentChunk
from app.models.user import User
from app.schemas.chat import MessageResponse
from app.services.rag import REFUSE_TEXT, answer_question

TITLE_LENGTH = 28  # 對話標題取第一個問題的前 28 字，和前端一致


def ask(db: Session, user: User, conversation: Conversation, content: str) -> Message:
    """存提問 → 呼叫 RAG → 存回答與出處，回傳助理的那則訊息。"""
    db.add(Message(conversation_id=conversation.id, role="user", content=content))
    if conversation.title is None:
        conversation.title = content[:TITLE_LENGTH]
    # 先 commit 提問：模型要跑好幾秒到幾十秒，這段期間就算出錯，問題本身也已經留下紀錄
    db.commit()

    started = time.perf_counter()
    result = answer_question(db, user, content)
    latency_ms = int((time.perf_counter() - started) * 1000)

    hits = result["citations"]
    # Hit 沒有版本欄位，另外查一次（一次查完所有出處，不要每個出處各查一次）
    versions = dict(
        db.execute(
            select(DocumentChunk.id, Document.version)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_([hit.chunk_id for hit in hits]))
        ).all()
    ) if hits else {}

    answer = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result["answer"],
        refused=result["answer"] == REFUSE_TEXT,
        latency_ms=latency_ms,
        citations=[
            MessageCitation(
                chunk_id=hit.chunk_id,
                rank=rank,
                doc_title=hit.doc_title,
                version=versions.get(hit.chunk_id),
                article_no=hit.article_no,
                score=hit.similarity,  # 用向量相似度（有絕對意義），不用只看名次的 RRF 分數
            )
            for rank, hit in enumerate(hits, start=1)
        ],
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)
    return answer


def to_responses(db: Session, user: User, messages: Sequence[Message]) -> list[MessageResponse]:
    """
    把訊息轉成回應格式，並補上出處的原文片段。

    原文片段「每次讀取時」依目前的權限重新檢查，而不是存在出處表裡：
    使用者可能已經換部門、文件可能已經改成限閱或作廢，當初看得到不代表現在還看得到。
    """
    chunk_ids = {c.chunk_id for m in messages for c in m.citations if c.chunk_id is not None}
    previews: dict[int, str] = {}
    if chunk_ids:
        previews = dict(
            db.execute(
                select(DocumentChunk.id, DocumentChunk.content)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(DocumentChunk.id.in_(chunk_ids), _visible_to(user))  # 和檢索用同一套權限條件
            ).all()
        )

    responses = []
    for message in messages:
        response = MessageResponse.model_validate(message)
        for citation_response, citation in zip(response.citations, message.citations):
            citation_response.preview = previews.get(citation.chunk_id)
        responses.append(response)
    return responses
