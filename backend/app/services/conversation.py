"""對話與訊息的讀寫。規則：只能操作自己的對話；別人的一律當作不存在（回 404）。

為什麼回 404 而不是 403：403 等於告訴對方「這個對話存在，只是你不能看」，
404 則不透露任何資訊。
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import AppError, not_found
from app.models import Conversation, Message, User
from app.models.chat import DEFAULT_TITLE


def get_owned(db: Session, *, user: User, conversation_id: uuid.UUID) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise not_found("找不到對話")
    return conversation


def create(db: Session, *, user: User, title: str | None) -> Conversation:
    conversation = Conversation(user_id=user.id, title=(title or "").strip() or DEFAULT_TITLE)
    db.add(conversation)
    db.commit()
    return conversation


def list_for_user(db: Session, *, user: User, limit: int, offset: int) -> tuple[list[Conversation], int]:
    query = select(Conversation).where(Conversation.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Conversation.created_at.desc()).limit(limit).offset(offset))
    return list(items), total


def delete(db: Session, *, user: User, conversation_id: uuid.UUID) -> None:
    """刪除自己的對話；訊息與出處由 cascade 一起刪除。"""
    db.delete(get_owned(db, user=user, conversation_id=conversation_id))
    db.commit()


def list_messages(db: Session, *, user: User, conversation_id: uuid.UUID) -> list[Message]:
    """對話內的訊息與出處。用 selectinload 一次載入全部出處，避免每則訊息各查一次（N+1 查詢）。"""
    conversation = get_owned(db, user=user, conversation_id=conversation_id)
    return list(db.scalars(
        select(Message).where(Message.conversation_id == conversation.id)
        .options(selectinload(Message.citations)).order_by(Message.id)))


def set_feedback(db: Session, *, user: User, message_id: int, value: str | None) -> Message:
    message = db.get(Message, message_id)
    if message is None:
        raise not_found("找不到訊息")
    get_owned(db, user=user, conversation_id=message.conversation_id)
    if message.role != "assistant":
        raise AppError(422, "not_assistant_message", "只能對 AI 回覆給回饋")
    message.feedback = value
    db.commit()
    return message
