"""資料表設計的驗收：刪除連動（CASCADE / SET NULL）與 CHECK 約束真的有在資料庫層生效。"""
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.models.audit import AuditLog, RefreshToken
from app.models.conversation import Conversation, Message, MessageCitation
from app.models.department import Department
from app.models.document import EMBEDDING_DIM, Document, DocumentChunk
from app.models.user import User


@pytest.fixture
def user(db):
    dept = Department(code="ops", name="ops")
    db.add(dept)
    db.flush()
    u = User(email="u@t.test", password_hash="x", dept_id=dept.id)
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def answered(db, user):
    """一段對話、一問一答、回答引用一個 chunk。"""
    doc = Document(dept_id=user.dept_id, title="SOP", version="v1", level="public", status="ready")
    db.add(doc)
    db.flush()
    chunk = DocumentChunk(document_id=doc.id, chunk_index=0, article_no="第1條", content="內文", embedding=[0.0] * EMBEDDING_DIM)
    conv = Conversation(user_id=user.id, title="測試")
    db.add_all([chunk, conv])
    db.flush()
    question = Message(conversation_id=conv.id, role="user", content="問題")
    answer = Message(conversation_id=conv.id, role="assistant", content="回答", latency_ms=1200)
    db.add_all([question, answer])
    db.flush()
    cite = MessageCitation(message_id=answer.id, chunk_id=chunk.id, rank=1, doc_title="SOP", version="v1", article_no="第1條", score=0.8)
    db.add(cite)
    db.flush()
    return dict(doc=doc, chunk=chunk, conv=conv, answer=answer, cite=cite)


def test_conversation_gets_uuid_and_defaults(db, answered):
    conv, answer = answered["conv"], answered["answer"]
    assert len(str(conv.id)) == 36
    db.refresh(answer)
    assert answer.refused is False  # server_default 生效
    assert answer.feedback is None  # 還沒評
    assert [m.role for m in conv.messages] == ["user", "assistant"]  # 依發送順序


def test_deleting_chunk_keeps_citation_snapshot(db, answered):
    # 文件被刪除 → chunk 連帶刪除（CASCADE）→ 出處的 chunk_id 變 NULL（SET NULL），但快照還在
    db.execute(delete(Document).where(Document.id == answered["doc"].id))
    db.expire_all()
    cite = db.get(MessageCitation, answered["cite"].id)
    assert cite.chunk_id is None
    assert (cite.doc_title, cite.version, cite.article_no) == ("SOP", "v1", "第1條")


def test_deleting_user_removes_conversations_but_keeps_audit_log(db, user, answered):
    db.add_all([
        AuditLog(user_id=user.id, action="ask", target=f"conversation:{answered['conv'].id}", ip="10.20.1.8"),
        RefreshToken(user_id=user.id, token_hash="a" * 64, expires_at=answered["conv"].created_at),
    ])
    db.flush()

    db.execute(delete(User).where(User.id == user.id))
    db.expire_all()

    assert db.scalar(select(Conversation)) is None  # 對話 CASCADE
    assert db.scalar(select(Message)) is None  # 訊息跟著對話 CASCADE
    assert db.scalar(select(MessageCitation)) is None  # 出處跟著訊息 CASCADE
    assert db.scalar(select(RefreshToken)) is None  # token CASCADE
    log = db.scalar(select(AuditLog))
    assert log is not None and log.user_id is None  # 稽核紀錄留下，只是操作者變 NULL


@pytest.mark.parametrize(
    "field,value",
    [("role", "system"), ("feedback", "meh")],
)
def test_message_check_constraints(db, answered, field, value):
    kwargs = dict(conversation_id=answered["conv"].id, role="assistant", content="x")
    kwargs[field] = value
    db.add(Message(**kwargs))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_audit_ip_must_be_valid(db, user):
    db.add(AuditLog(user_id=user.id, action="login.success", ip="not-an-ip"))
    with pytest.raises(Exception):  # INET 型別拒絕格式錯誤的 IP（DataError）
        db.flush()
    db.rollback()


def test_refresh_token_hash_is_unique(db, user):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db.add_all([
        RefreshToken(user_id=user.id, token_hash="b" * 64, expires_at=now),
        RefreshToken(user_id=user.id, token_hash="b" * 64, expires_at=now),
    ])
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
