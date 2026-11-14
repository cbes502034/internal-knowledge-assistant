"""註冊、登入、權杖輪替、閒置登出、帳號鎖定、停用。"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.main import create_app
from app.models import AuditLog, RefreshToken, User
from tests.fakes import PASSWORD, login, make_user, register

pytestmark = pytest.mark.db

REFRESH = {"grant_type": "refresh_token"}


def test_register_login_me_logout(client):
    assert register(client, "a@example.com").status_code == 201
    r = login(client, "A@Example.com ")                      # email 不分大小寫、會去掉空白
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.cookies.get("refresh_token")              # refresh token 放在 cookie

    me = client.get("/api/v1/me", headers=headers).json()
    assert me["email"] == "a@example.com" and me["department"]["code"] == "ops" and me["role"] == "employee"

    assert client.post("/api/v1/auth/revoke", headers=headers).status_code == 204
    assert client.post("/api/v1/auth/token", data=REFRESH).status_code == 401


def test_duplicate_email_and_unknown_department(client):
    assert register(client, "a@example.com").status_code == 201
    assert register(client, "a@example.com").json()["code"] == "email_taken"
    assert register(client, "b@example.com", dept="nope").json()["code"] == "unknown_department"


def test_wrong_password_and_unknown_email_get_the_same_answer(client):
    register(client, "a@example.com")
    wrong = login(client, "a@example.com", "wrong-password")
    unknown = login(client, "nobody@example.com", "wrong-password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_refresh_rotates_token_and_detects_reuse(client):
    register(client, "a@example.com")
    login(client, "a@example.com")
    old = client.cookies.get("refresh_token")

    assert client.post("/api/v1/auth/token", data=REFRESH).status_code == 200
    new = client.cookies.get("refresh_token")
    assert new and new != old

    # 有人拿舊的（已輪替作廢的）token 來換：視為外洩，撤銷此人全部 token
    attacker = TestClient(create_app())
    stolen = attacker.post("/api/v1/auth/token", data=REFRESH, headers={"Cookie": f"refresh_token={old}"})
    assert stolen.status_code == 401
    assert client.post("/api/v1/auth/token", data=REFRESH).status_code == 401      # 連新的也失效

    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "token.reuse_detected")) is not None
        assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


def test_idle_user_must_log_in_again(client):
    headers = make_user(client, "a@example.com")
    with SessionLocal() as db:
        db.execute(update(User).values(last_active_at=datetime.now(timezone.utc) - timedelta(minutes=20)))
        db.commit()
    r = client.get("/api/v1/me", headers=headers)
    assert r.status_code == 401 and r.json()["code"] == "idle_timeout"
    assert client.post("/api/v1/auth/token", data=REFRESH).json()["code"] == "idle_timeout"


def test_account_locks_after_repeated_failures(client):
    register(client, "a@example.com")
    for _ in range(5):
        assert login(client, "a@example.com", "wrong-password").status_code == 401
    locked = login(client, "a@example.com", PASSWORD)            # 密碼正確也進不去
    assert locked.status_code == 429 and locked.json()["code"] == "too_many_attempts"
    assert int(locked.headers["Retry-After"]) > 0


def test_disabling_a_user_takes_effect_immediately(client):
    user_headers = make_user(client, "a@example.com")
    admin_headers = make_user(client, "it@example.com", dept="gm_office", role="it_admin")
    user_id = client.get("/api/v1/me", headers=user_headers).json()["id"]

    r = client.patch(f"/api/v1/users/{user_id}", json={"is_active": False}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/v1/me", headers=user_headers).status_code == 401   # 舊的 access JWT 立刻失效


def test_admin_cannot_demote_self_and_employee_cannot_manage_users(client):
    admin_headers = make_user(client, "it@example.com", dept="gm_office", role="it_admin")
    admin_id = client.get("/api/v1/me", headers=admin_headers).json()["id"]
    r = client.patch(f"/api/v1/users/{admin_id}", json={"role": "employee"}, headers=admin_headers)
    assert r.status_code == 422 and r.json()["code"] == "self_modification"

    user_headers = make_user(client, "a@example.com")
    assert client.get("/api/v1/users", headers=user_headers).status_code == 403
    page = client.get("/api/v1/users?dept=gm_office", headers=admin_headers).json()
    assert page["total"] == 1 and page["items"][0]["email"] == "it@example.com"
