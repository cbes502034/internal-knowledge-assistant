"""問答：權限過濾、出處、拒答、模型故障、回饋、限流。"""
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core import retriever
from app.db import SessionLocal
from app.models import Department, Message
from app.services import document as document_service
from tests.fakes import make_user

pytestmark = pytest.mark.db

WASTE_SOP = "廢棄物處理SOP\n第1條 廢溶劑須以專用容器收集。\n第2條 廢溶劑暫存超過90天須聯絡合格清運廠商處理。\n"
DESIGN_RULE = "設計文件管制辦法\n第1條 設計變更須提出工程變更通知並經研發主管核准。\n"
EMERGENCY = "緊急應變SOP\n第1條 發現化學品洩漏應立即通報環安值班人員。\n第15-1條 洩漏處理人員須穿戴防護具。\n"


def add_document(title: str, text: str, dept: str, level: str):
    with SessionLocal() as db:
        document = document_service.upload(db, actor=None, filename=f"{title}.txt", data=text.encode(),
                                           title=title, dept_code=dept, level=level, version="v1",
                                           effective_date=None)
        document = document_service.process(db, document)
        assert document.status == "ready"
        return document.id


@pytest.fixture
def corpus():
    add_document("廢棄物處理SOP", WASTE_SOP, "ops", "dept")
    add_document("設計文件管制辦法", DESIGN_RULE, "rd", "restricted")
    add_document("緊急應變SOP", EMERGENCY, "ops", "public")


def ask(client, headers, question):
    conversation = client.post("/api/v1/conversations", json={}, headers=headers).json()
    return conversation, client.post(f"/api/v1/conversations/{conversation['id']}/messages",
                                     json={"content": question}, headers=headers)


def asker(dept_code: str, role: str = "employee"):
    with SessionLocal() as db:
        dept_id = db.scalar(select(Department.id).where(Department.code == dept_code))
    return SimpleNamespace(dept_id=dept_id, role=role)


def search_titles(question: str, user) -> set[str]:
    with SessionLocal() as db:
        return {hit.doc_title for hit in retriever.hybrid_search(db, question=question, user=user, k=5)}


def test_answer_has_citations_and_conversation_gets_a_title(client, corpus, fake_llm):
    headers = make_user(client, "ops@example.com", dept="ops")
    conversation, r = ask(client, headers, "廢溶劑放多久要處理")
    assert r.status_code == 201
    reply = r.json()
    assert reply["refused"] is False and reply["latency_ms"] is not None
    assert reply["citations"][0]["doc_title"] == "廢棄物處理SOP"            # 模型回答 [1]，只列出第 1 筆
    assert reply["citations"][0]["locator"] in {"第1條", "第2條"}
    assert "<資料>" in fake_llm.last_prompt and "只能根據" in fake_llm.last_system

    messages = client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=headers).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    titles = client.get("/api/v1/conversations", headers=headers).json()["items"]
    assert titles[0]["title"] == "廢溶劑放多久要處理"


def test_department_and_restricted_documents_are_filtered_in_sql(corpus):
    assert "廢棄物處理SOP" in search_titles("廢溶劑放多久要處理", asker("ops"))
    assert "廢棄物處理SOP" not in search_titles("廢溶劑放多久要處理", asker("sales"))       # 別的部門
    assert "設計文件管制辦法" not in search_titles("設計變更要誰核准", asker("rd"))           # 限閱：員工看不到
    assert "設計文件管制辦法" in search_titles("設計變更要誰核准", asker("rd", "manager"))     # 限閱：主管看得到
    assert "設計文件管制辦法" not in search_titles("設計變更要誰核准", asker("ops", "manager"))
    assert "緊急應變SOP" in search_titles("化學品洩漏要通知誰", asker("sales"))               # 公開


def test_unrelated_question_is_refused_without_calling_the_model(client, corpus, fake_llm):
    headers = make_user(client, "ops@example.com", dept="ops")
    _, r = ask(client, headers, "員工餐廳幾點開放")
    assert r.json()["refused"] is True and r.json()["citations"] == []
    assert fake_llm.generated == 0


def test_model_saying_not_found_is_recorded_as_refusal(client, corpus, fake_llm):
    fake_llm.answer = "找不到相關規定。"
    headers = make_user(client, "ops@example.com", dept="ops")
    _, r = ask(client, headers, "廢溶劑放多久要處理")
    assert r.json()["refused"] is True and r.json()["citations"] == []


def test_sub_article_locator(client, corpus):
    headers = make_user(client, "ops@example.com", dept="ops")
    _, r = ask(client, headers, "洩漏處理人員要穿戴什麼")
    assert any(c["locator"] == "第15-1條" for c in r.json()["citations"]) or r.json()["citations"][0]["doc_title"] == "緊急應變SOP"


def test_model_failure_returns_503_and_saves_nothing(client, corpus, fake_llm):
    headers = make_user(client, "ops@example.com", dept="ops")
    conversation = client.post("/api/v1/conversations", json={}, headers=headers).json()
    fake_llm.down = True
    r = client.post(f"/api/v1/conversations/{conversation['id']}/messages",
                    json={"content": "廢溶劑放多久要處理"}, headers=headers)
    assert r.status_code == 503 and r.json()["code"] == "llm_unavailable"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Message.id))) == 0


def test_other_users_cannot_read_or_rate_my_conversation(client, corpus):
    mine = make_user(client, "ops@example.com", dept="ops")
    other = make_user(client, "ops2@example.com", dept="ops")
    conversation, r = ask(client, mine, "廢溶劑放多久要處理")
    reply_id = r.json()["id"]

    assert client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=other).status_code == 404
    assert client.put(f"/api/v1/messages/{reply_id}/feedback", json={"value": "up"}, headers=other).status_code == 404
    rated = client.put(f"/api/v1/messages/{reply_id}/feedback", json={"value": "up"}, headers=mine)
    assert rated.status_code == 200 and rated.json()["feedback"] == "up"


def test_rate_limit_returns_429(client, corpus, monkeypatch):
    from app import deps
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 2)
    deps._ask_limiter.cache_clear()
    headers = make_user(client, "ops@example.com", dept="ops")
    statuses = [ask(client, headers, "廢溶劑放多久要處理")[1].status_code for _ in range(3)]
    assert statuses[:2] == [201, 201] and statuses[2] == 429
