import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (ConversationCreate, ConversationOut, FeedbackIn, MessageCreate, MessageOut, Page)
from app.services import conversation as conversation_service
from app.services import rag as rag_service

router = APIRouter(tags=["conversations"])


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(body: ConversationCreate, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    return conversation_service.create(db, user=user, title=body.title)


@router.get("/conversations", response_model=Page[ConversationOut])
def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = conversation_service.list_for_user(db, user=user, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    conversation_service.delete(db, user=user, conversation_id=conversation_id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: uuid.UUID, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    return conversation_service.list_messages(db, user=user, conversation_id=conversation_id)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=201)
def ask(conversation_id: uuid.UUID, body: MessageCreate, user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    """提問：在對話下新增一則訊息，回傳 AI 回覆（含出處、耗時）。"""
    return rag_service.answer_question(db, user=user, conversation_id=conversation_id, content=body.content)


@router.put("/messages/{message_id}/feedback", response_model=MessageOut)
def set_feedback(message_id: int, body: FeedbackIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return conversation_service.set_feedback(db, user=user, message_id=message_id, value=body.value)
