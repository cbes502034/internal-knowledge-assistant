"""
對話與問答 API：每個登入者都能用，但只能碰「自己的」對話。
對應職缺：RESTful API、RAG 應用落地、資料權限（物件層級的存取控制）。

為什麼別人的對話回 404 而不是 403？
403 等於告訴對方「這個編號的對話存在，只是你不能看」，404 則不透露任何資訊。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.schemas.chat import AskRequest, FeedbackRequest, MessageResponse
from app.schemas.common import Page
from app.schemas.conversation import ConversationCreate, ConversationResponse
from app.services.audit import log_event
from app.services.chat import ask, to_responses

router = APIRouter(prefix="/api/v1", tags=["conversations"])


def _own_conversation(db: Session, user: User, conversation_id: uuid.UUID) -> Conversation:
    """取得對話並確認是本人的；不是本人的和不存在的一樣回 404。"""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "對話不存在")
    return conversation


@router.get("/conversations", response_model=Page[ConversationResponse])
def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """我的對話列表，新的在前。查詢條件一定帶 user_id：資料權限寫在查詢裡，不是查完再過濾。"""
    mine = select(Conversation).where(Conversation.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(mine.subquery()))
    items = db.scalars(mine.order_by(Conversation.created_at.desc()).limit(limit).offset(offset)).all()
    return Page(items=items, total=total)


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = Conversation(user_id=user.id, title=data.title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """刪除對話；訊息與出處由資料庫的 ON DELETE CASCADE 一起刪掉。成功回 204（沒有內容）。"""
    db.delete(_own_conversation(db, user, conversation_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _own_conversation(db, user, conversation_id)
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(selectinload(Message.citations))  # 一次撈完所有出處，避免每則訊息各查一次（N+1 問題）
        .order_by(Message.id)
    ).all()
    return to_responses(db, user, messages)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_message(
    conversation_id: uuid.UUID,
    data: AskRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    提問：存問題 → RAG 回答 → 存回答與出處，回傳助理的訊息。
    這個端點用一般 def（不是 async def）：裡面的資料庫與模型呼叫都是同步的，
    FastAPI 會把它丟到執行緒池跑，模型生成的幾十秒不會卡住其他人的請求。
    """
    conversation = _own_conversation(db, user, conversation_id)
    answer = ask(db, user, conversation, data.content)
    # 稽核只記「誰在哪個對話問了問題」，不記問題內容
    log_event(db, request, "ask", user_id=user.id, target=f"conversation:{conversation.id}")
    return to_responses(db, user, [answer])[0]


@router.put("/messages/{message_id}/feedback", response_model=MessageResponse)
def set_feedback(
    message_id: int,
    data: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """對回答按「有用／沒用」；再按一次同一個值就取消（和前端的切換行為一致）。"""
    message = db.get(Message, message_id)
    if message is None or message.role != "assistant" or message.conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "訊息不存在")

    message.feedback = None if message.feedback == data.value else data.value
    db.commit()
    db.refresh(message)
    return to_responses(db, user, [message])[0]
