"""資料表定義（對應企劃書 6.3）。從這裡匯入，Alembic 才看得到全部資料表。"""
from app.models.base import Base
from app.models.org import Department, RefreshToken, User
from app.models.document import Chunk, Document
from app.models.chat import Conversation, Message, MessageCitation
from app.models.audit import AuditLog
from app.models.eval import EvalCase, EvalResult, EvalRun

__all__ = [
    "Base", "Department", "User", "RefreshToken", "Document", "Chunk",
    "Conversation", "Message", "MessageCitation", "AuditLog",
    "EvalCase", "EvalRun", "EvalResult",
]
