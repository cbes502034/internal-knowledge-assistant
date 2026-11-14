"""評測批次、越權檢查、稽核紀錄、資料表與遷移一致。"""
import pytest

from app.db import SessionLocal
from app.models import EvalCase
from tests.fakes import make_user
from tests.integration.test_rag import corpus  # noqa: F401  共用文件資料

pytestmark = pytest.mark.db


def add_cases():
    with SessionLocal() as db:
        db.add_all([
            EvalCase(question="廢溶劑放多久要處理", expected_doc_title="廢棄物處理SOP", expected_article_no=2,
                     as_dept="ops", as_role="employee", should_refuse=False),
            EvalCase(question="員工餐廳幾點開放", as_dept="ops", as_role="employee", should_refuse=True),
            EvalCase(question="廢溶劑放多久要處理", expected_doc_title="廢棄物處理SOP", expected_article_no=2,
                     as_dept="sales", as_role="employee", should_refuse=False),       # 越權題
            EvalCase(question="設計變更要誰核准", expected_doc_title="設計文件管制辦法", expected_article_no=1,
                     as_dept="rd", as_role="employee", should_refuse=False),          # 越權題（限閱）
        ])
        db.commit()


def test_eval_run_reports_metrics_and_no_leaks(client, corpus):  # noqa: F811
    add_cases()
    admin = make_user(client, "it@example.com", dept="gm_office", role="it_admin")
    run = client.post("/api/v1/eval-runs", json={"mode": "hybrid"}, headers=admin)
    assert run.status_code == 202

    runs = client.get("/api/v1/eval-runs", headers=admin).json()["items"]
    metrics = runs[0]["metrics"]
    assert metrics["cases"] == 4 and metrics["leaks"] == 0 and metrics["permission_pass"] == 1.0
    assert metrics["hit_at_3"] == 1.0 and metrics["refuse_accuracy"] == 1.0

    results = client.get(f"/api/v1/eval-runs/{run.json()['id']}/results", headers=admin).json()
    assert sorted(r["kind"] for r in results) == ["answer", "permission", "permission", "refuse"]
    failed = client.get(f"/api/v1/eval-runs/{run.json()['id']}/results?failed_only=true", headers=admin).json()
    assert failed == []


def test_audit_log_is_visible_to_it_only(client):
    admin = make_user(client, "it@example.com", dept="gm_office", role="it_admin")
    user = make_user(client, "ops@example.com", dept="ops")
    assert client.get("/api/v1/audit-logs", headers=user).status_code == 403
    actions = {item["action"] for item in client.get("/api/v1/audit-logs", headers=admin).json()["items"]}
    assert {"user.register", "login"} <= actions


def test_models_and_migrations_are_in_sync(database):
    from alembic import command
    command.check(database)          # models 有改但沒產生遷移檔時會失敗
