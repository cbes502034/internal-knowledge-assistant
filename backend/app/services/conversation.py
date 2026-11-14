"""對話與訊息的讀寫。規則：只能操作自己的對話；別人的一律當作不存在（回 404）。"""
import uuid

from sqlalchemy.orm import Session

from app.models import Conversation, Message, User


def get_owned(db: Session, *, user: User, conversation_id: uuid.UUID) -> Conversation:
    """TODO：取得「屬於這位使用者」的對話，其他函式都先呼叫它。

    1. db.get(Conversation, conversation_id)
    2. 不存在，或 user_id 不是這位使用者 → raise not_found("找不到對話")
       （為什麼別人的對話回 404 而不是 403？）
    """
    raise NotImplementedError("services.conversation.get_owned 尚未實作")


def create(db: Session, *, user: User, title: str | None) -> Conversation:
    """TODO：新增對話。title 為空時用預設值。"""
    raise NotImplementedError("services.conversation.create 尚未實作")


def list_for_user(db: Session, *, user: User, limit: int, offset: int) -> tuple[list[Conversation], int]:
    """TODO：自己的對話列表，新的在前。回傳 (這一頁, 總筆數)。"""
    raise NotImplementedError("services.conversation.list_for_user 尚未實作")


def delete(db: Session, *, user: User, conversation_id: uuid.UUID) -> None:
    """TODO：刪除自己的對話（訊息與出處會連動刪除，見 models/chat.py 的 cascade）。"""
    raise NotImplementedError("services.conversation.delete 尚未實作")


def list_messages(db: Session, *, user: User, conversation_id: uuid.UUID) -> list[Message]:
    """TODO：對話內的訊息（含出處），依時間排序。

    提示：先 get_owned，再回傳 conversation.messages；
    訊息多時會有 N+1 查詢問題，可用 selectinload(Message.citations) 一次載入。
    """
    raise NotImplementedError("services.conversation.list_messages 尚未實作")


def set_feedback(db: Session, *, user: User, message_id: int, value: str | None) -> Message:
    """TODO：設定某則 AI 回覆的回饋（up／down／None）。

    1. 取得訊息；不存在 → not_found
    2. 用 get_owned 確認這則訊息的對話屬於這位使用者
    3. 只有 role="assistant" 的訊息可以被回饋，否則 AppError(422, ...)
    4. 更新 feedback、commit、回傳
    """
    raise NotImplementedError("services.conversation.set_feedback 尚未實作")
