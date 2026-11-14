"""需要資料庫的測試：docker compose up -d db、alembic upgrade head、python -m scripts.seed 之後
執行  pytest -m db
"""
import pytest

pytestmark = pytest.mark.db


def test_db_health(client):
    assert client.get("/api/v1/health/db").status_code == 200


def test_departments_endpoint_returns_seeded_departments(client):
    r = client.get("/api/v1/departments")
    assert r.status_code == 200
    assert {d["code"] for d in r.json()} >= {"sales", "product", "rd", "ops", "finance", "gm_office"}
