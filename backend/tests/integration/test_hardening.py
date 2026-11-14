"""審查後補上的行為：多分頁同時更新權杖、關閉註冊、評測失敗、啟動復原、上傳上限、預設密鑰。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.config import get_settings
from app.db import SessionLocal
from app.main import create_app
from app.models import AuditLog, Document, EvalCase
from tests.fakes import login, make_user, register

pytestmark = pytest.mark.db

REFRESH = {"grant_type": "refresh_token"}


def test_two_tabs_refreshing_at_once_are_not_treated_as_theft(client):
    register(client, "a@example.com")
    login(client, "a@example.com")
    old = client.cookies.get("refresh_token")
    assert client.post("/api/v1/auth/token", data=REFRESH).status_code == 200     # 分頁 A 先換到新的

    tab_b = TestClient(create_app())                                                # 分頁 B 幾乎同時送出舊的
    r = tab_b.post("/api/v1/auth/token", data=REFRESH, headers={"Cookie": f"refresh_token={old}"})
    assert r.status_code == 401 and r.json()["code"] == "refresh_superseded"
    assert client.post("/api/v1/auth/token", data=REFRESH).status_code == 200     # 新的仍然有效，沒有被全部撤銷
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "token.reuse_detected")) is None


def test_registration_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_registration", False)
    r = register(client, "a@example.com")
    assert r.status_code == 403 and r.json()["code"] == "registration_disabled"


def test_failed_eval_run_is_reported_instead_of_running_forever(client, fake_llm):
    admin = make_user(client, "it@example.com", dept="gm_office", role="it_admin")
    with SessionLocal() as db:
        db.add(EvalCase(question="任何問題", as_dept="ops", as_role="employee", should_refuse=True))
        db.commit()
    fake_llm.down = True
    assert client.post("/api/v1/eval-runs", json={}, headers=admin).status_code == 202
    run = client.get("/api/v1/eval-runs", headers=admin).json()["items"][0]
    assert run["error"] == "AI 服務無法使用" and run["finished_at"] is not None and run["metrics"] is None


def test_documents_interrupted_by_a_restart_are_marked_failed_on_startup(client):
    admin = make_user(client, "it@example.com", dept="gm_office", role="it_admin")
    r = client.post("/api/v1/documents", data={"title": "中斷的文件", "dept_code": "ops"},
                    files={"file": ("a.txt", "第1條 甲。".encode(), "text/plain")}, headers=admin)
    document_id = r.json()["id"]
    with SessionLocal() as db:                       # 模擬處理到一半服務被重啟
        db.execute(update(Document).where(Document.id == document_id).values(status="pending"))
        db.commit()
    assert client.post(f"/api/v1/documents/{document_id}/processing-jobs", headers=admin).status_code == 409

    with TestClient(create_app()):                   # with 區塊會觸發啟動流程
        pass
    with SessionLocal() as db:
        assert db.get(Document, document_id).status == "failed"
    assert client.post(f"/api/v1/documents/{document_id}/processing-jobs", headers=admin).status_code == 202


def test_oversized_upload_is_rejected(client, monkeypatch):
    admin = make_user(client, "it@example.com", dept="gm_office", role="it_admin")
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    big = b"x" * (1024 * 1024 + 10)
    r = client.post("/api/v1/documents", data={"title": "太大", "dept_code": "ops"},
                    files={"file": ("big.txt", big, "text/plain")}, headers=admin)
    assert r.status_code == 413 and r.json()["code"] == "file_too_large"


def test_app_refuses_to_start_with_the_template_jwt_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", "change-me-generate-a-long-random-string")
    with pytest.raises(RuntimeError):
        create_app()
