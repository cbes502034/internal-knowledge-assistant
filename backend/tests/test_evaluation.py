"""
【檔案用途】RAG 評測的測試：指標公式、逐題流程（含權限題與拒答題）、失敗處理、評測 API。
模型用假的（不需要 Ollama）；資料庫用臨時測試庫。

執行：在 backend 目錄 .venv\\Scripts\\python.exe -m pytest tests/test_evaluation.py -q
"""
import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.llm_service import LLMUnavailableError
from app.core.retriever import Hit
from app.core.security import hashPassword
from app.main import app
from app.models.department import Department
from app.models.document import EMBEDDING_DIM
from app.models.evaluation import EvalResult, EvalRun
from app.models.user import User
from app.services import evaluation, ingestion
from app.services.evaluation import (
    EvalAlreadyRunningError,
    compute_metrics,
    find_rank,
    is_failure,
    load_cases,
    mark_interrupted_runs,
    percentile,
    run_evaluation,
    start_run,
)

PASSWORD = "test-password-123"


class FakeLLM:
    """假模型：嵌入用「字元出現次數」當向量（字越像、相似度越高）；生成回固定句子。"""
    fail = False  # 設成 True 時模擬模型服務掛掉

    def __init__(self, *args, **kwargs):
        pass

    def embed(self, text):
        if FakeLLM.fail:
            raise LLMUnavailableError("down")
        v = [0.0] * EMBEDDING_DIM
        for ch in text:
            v[ord(ch) % EMBEDDING_DIM] += 1.0
        return v

    def generate(self, prompt):
        return "依據參考資料回答。"


# 小題庫：三題該回答、兩題越權（應拒答）、一題題庫外（應拒答）
# 第 5、6 題問同一份限閱文件：員工問要拒答、IT 管理員問要回答——驗證評測真的用「題目指定的身分」提問
CASES = [
    {"question": "廢溶劑暫存期限不得超過幾天", "kind": "answer", "expected_doc_title": "廢棄物SOP", "expected_article_no": "第1條", "as_dept": "ops"},
    {"question": "出差住宿費每晚上限多少", "kind": "answer", "expected_doc_title": "差旅辦法", "expected_article_no": "第1條", "as_dept": "sales"},
    {"question": "出差住宿費每晚上限多少", "kind": "permission", "as_dept": "ops"},
    {"question": "ZZZ QQQ", "kind": "refuse", "as_dept": "ops"},
    {"question": "資安事件須於多久內通報", "kind": "permission", "as_dept": "ops"},
    {"question": "資安事件須於多久內通報", "kind": "answer", "expected_doc_title": "資安通報", "expected_article_no": "第1條", "as_dept": "ops", "as_role": "it_admin"},
]


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """上傳檔放暫存資料夾、題庫換成上面的小題庫、模型換成假的。"""
    FakeLLM.fail = False
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(evaluation, "CASES_PATH", cases_file)
    monkeypatch.setattr(evaluation, "LLMService", FakeLLM)


@pytest.fixture
def world(db):
    """營運部、業務部；公開文件（營運部）、部門限定文件（業務部）、限閱文件（只有 IT 管理員看得到）。"""
    depts = {code: Department(code=code, name=code) for code in ("ops", "sales")}
    db.add_all(depts.values())
    db.flush()
    for title, dept, level, content in [
        ("廢棄物SOP", "ops", "public", "第1條 廢溶劑暫存期限不得超過九十天。"),
        ("差旅辦法", "sales", "dept", "第1條 出差住宿費每晚上限三千元。"),
        ("資安通報", "ops", "restricted", "第1條 資安事件須於一小時內通報。"),
    ]:
        doc = ingestion.register_upload(
            db, filename=f"{title}.txt", raw=content.encode("utf-8"),
            dept_id=depts[dept].id, title=title, version="v1", level=level,
        )
        ingestion.process_document(db, doc.id, llm=FakeLLM())
    return depts


def result(kind, hit_rank=None, refused=False, latency_ms=100):
    """建一個不存進資料庫的 EvalResult，給純計算的測試用。"""
    return EvalResult(case_no=1, question="q", kind=kind, hit_rank=hit_rank, refused=refused, latency_ms=latency_ms)


# ───────────────────────── 指標公式（不需要資料庫）─────────────────────────

def test_find_rank():
    hits = [Hit(1, "A", "第1條", "", 0.0), Hit(2, "B", "第2條", "", 0.0)]
    assert find_rank(hits, "B", "第2條") == 2
    assert find_rank(hits, "B", "第9條") is None


def test_percentile_nearest_rank():
    values = list(range(1, 101))  # 1..100
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([], 95) == 0
    assert percentile([7], 50) == 7


def test_compute_metrics():
    results = [
        result("answer", hit_rank=1, latency_ms=100),
        result("answer", hit_rank=2, latency_ms=200),
        result("answer", hit_rank=None, latency_ms=300),
        result("answer", hit_rank=1, refused=True, latency_ms=400),  # 檢索排第一，但被誤拒
        result("refuse", refused=True, latency_ms=50),
        result("permission", refused=False, latency_ms=60),  # 漏拒
    ]
    m = compute_metrics(results)
    assert m["cases"] == 6 and m["answerable"] == 4
    assert m["hit_at_1"] == 0.5  # 4 題中 2 題排第一
    assert m["hit_at_3"] == 0.75  # 第 2 名也算進前 3
    assert m["mrr"] == pytest.approx((1 + 0.5 + 0 + 1) / 4, abs=1e-4)
    assert m["refuse_accuracy"] == pytest.approx(4 / 6, abs=1e-4)  # 錯 2 題：誤拒 1、漏拒 1
    assert (m["false_refusals"], m["missed_refusals"]) == (1, 1)
    # 排序後 50、60、100、200、300、400：p50 取第 ceil(3) 個 = 100，p95 取第 ceil(5.7) 個 = 400
    assert m["p50_ms"] == 100 and m["p95_ms"] == 400


def test_second_line_of_defense_is_counted():
    caught = result("permission", refused=False)
    caught.answer = "找不到依據"  # 門檻沒擋，模型自己拒答
    bad = result("answer", hit_rank=1)
    bad.answer = "找不到依據"  # 應回答，模型卻不肯答
    good = result("answer", hit_rank=1)
    good.answer = "依據第3條，九十天。"
    m = compute_metrics([caught, bad, good])
    assert m["missed_refusals_caught_by_prompt"] == 1
    assert m["answers_declined_by_model"] == 1


def test_is_failure():
    assert not is_failure(result("answer", hit_rank=1))
    assert is_failure(result("answer", hit_rank=2))  # 沒排第一
    assert is_failure(result("answer", hit_rank=1, refused=True))  # 被誤拒
    assert not is_failure(result("permission", refused=True))
    assert is_failure(result("refuse", refused=False))  # 該拒答卻回答


def test_load_cases_validates(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"question": "q", "kind": "answer", "as_dept": "ops"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(bad)  # answer 題沒有標準答案


def test_real_case_file_is_valid():
    """專案附的題庫（backend/data/eval_cases.json）格式正確，三類題目都有。"""
    cases = load_cases(evaluation.Path(__file__).resolve().parents[1] / "data" / "eval_cases.json")
    assert {c["kind"] for c in cases} == {"answer", "refuse", "permission"}
    assert len(cases) >= 20


# ───────────────────────── 逐題流程 ─────────────────────────

def test_run_evaluation_end_to_end(db, world):
    run = run_evaluation(db, start_run(db).id, llm=FakeLLM())

    assert run.status == "done" and run.finished_at is not None
    assert run.metrics["hit_at_1"] == 1.0
    assert run.metrics["refuse_accuracy"] == 1.0
    results = db.scalars(select(EvalResult).where(EvalResult.run_id == run.id).order_by(EvalResult.case_no)).all()
    assert [r.refused for r in results] == [False, False, True, True, True, False]
    assert results[0].answer and results[2].answer is None  # 拒答就不生成
    assert results[2].top_hit is None or "差旅辦法" not in results[2].top_hit  # 越權題看不到業務部的文件
    assert results[4].top_hit is None or "資安通報" not in results[4].top_hit  # 員工看不到限閱文件
    assert results[5].hit_rank == 1  # 同一題以 IT 管理員身分問，就找得到
    assert run.config["min_similarity"] == evaluation.MIN_SIMILARITY  # 記下當時的參數


def test_run_failure_marks_failed_and_keeps_no_results(db, world):
    run = start_run(db)
    FakeLLM.fail = True
    with pytest.raises(LLMUnavailableError):
        run_evaluation(db, run.id, llm=FakeLLM())
    db.expire_all()
    failed = db.get(EvalRun, run.id)
    assert failed.status == "failed" and "down" in failed.error
    assert db.scalar(select(EvalResult)) is None  # 做到一半的結果被 rollback


def test_only_one_run_at_a_time(db, world):
    start_run(db)
    with pytest.raises(EvalAlreadyRunningError):
        start_run(db)


def test_restart_marks_running_as_failed(db, world):
    run = start_run(db)
    assert mark_interrupted_runs(db) == 1
    db.expire_all()
    assert db.get(EvalRun, run.id).status == "failed"


# ───────────────────────── 評測 API ─────────────────────────

@pytest.fixture
def client(db, monkeypatch, world):
    @contextmanager
    def same_session():
        yield db

    monkeypatch.setattr(ingestion, "session_scope", same_session)  # 背景工作用測試的 session
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def login_as(client, db, world, email, role):
    db.add(User(email=email, password_hash=hashPassword(PASSWORD), dept_id=world["ops"].id, role=role))
    db.flush()
    r = client.post("/api/v1/auth/token", data={"grant_type": "password", "username": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_eval_api_flow(client, db, world):
    admin = login_as(client, db, world, "admin@company.com", "it_admin")

    r = client.post("/api/v1/eval-runs", headers=admin, json={})
    assert r.status_code == 202 and r.json()["status"] == "running"  # 回應當下還在跑
    run_id = r.json()["id"]

    runs = client.get("/api/v1/eval-runs", headers=admin).json()
    assert runs["total"] == 1 and runs["items"][0]["status"] == "done"  # 背景工作跑完
    assert runs["items"][0]["metrics"]["hit_at_1"] == 1.0

    results = client.get(f"/api/v1/eval-runs/{run_id}/results", headers=admin).json()
    assert [x["case_id"] for x in results] == [1, 2, 3, 4, 5, 6]  # 前端用 case_id 顯示題號
    assert client.get(f"/api/v1/eval-runs/{run_id}/results?failed_only=true", headers=admin).json() == []
    assert client.get("/api/v1/eval-runs/999/results", headers=admin).status_code == 404


def test_eval_api_is_admin_only(client, db, world):
    employee = login_as(client, db, world, "emp@company.com", "employee")
    assert client.get("/api/v1/eval-runs", headers=employee).status_code == 403
    assert client.post("/api/v1/eval-runs", headers=employee, json={}).status_code == 403


def test_eval_api_rejects_concurrent_run(client, db, world):
    admin = login_as(client, db, world, "admin@company.com", "it_admin")
    start_run(db)  # 已經有一個在跑
    assert client.post("/api/v1/eval-runs", headers=admin, json={}).status_code == 409
