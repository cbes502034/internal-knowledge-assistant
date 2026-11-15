"""
【檔案用途】API 整合測試：用 FastAPI 的 TestClient 走真正的 HTTP 流程（路由 → 依賴注入 → 服務 → 資料庫）。
資料庫用臨時測試庫（tests/conftest.py 建立）；模型用假的（不需要 Ollama），
所以測的是「系統接起來對不對」，不是模型好不好。

執行：在 backend 目錄 .venv\\Scripts\\python.exe -m pytest tests/test_api.py -q

測試分區：註冊與登入／refresh token／權限（RBAC）／文件入庫／對話與問答／稽核
"""
from contextlib import contextmanager  # 做一個「假的 session_scope」，讓背景工作用測試的 session
from datetime import datetime, timedelta, timezone  # 竄改時間（模擬 token 作廢很久、使用者閒置很久）

import pytest  # 測試框架：fixture、parametrize、raises
from fastapi.testclient import TestClient  # 不用真的開伺服器，就能對 app 發 HTTP 請求
from sqlalchemy import select, update  # 直接查或改資料庫，驗證 API 的效果

from app.core.config import settings  # 改上傳資料夾、讀閒置分鐘數
from app.core.database import get_db  # 要被覆寫的依賴：讓 API 用測試的 session
from app.core.security import hashPassword  # 直接在資料庫建立使用者時要先雜湊密碼
from app.main import app  # 被測試的應用程式
from app.models.audit import AuditLog, RefreshToken  # 驗證稽核紀錄與 token 狀態
from app.models.department import Department  # 建立測試用部門
from app.models.document import EMBEDDING_DIM, Document  # 假向量的維度、驗證文件狀態
from app.models.user import User  # 建立測試用使用者
from app.services import ingestion, rag  # 要被替換掉 LLMService 與 session_scope 的兩個模組
from app.services.rag import REFUSE_TEXT  # 比對拒答文字

PASSWORD = "test-password-123"  # 所有測試帳號共用的密碼（只存在臨時測試庫）
SOP = "廢棄物處理SOP\n第1條 廢溶劑暫存期限不得超過九十天。\n第2條 廢溶劑容器應標示內容物與日期。"


class FakeLLM:
    """假模型：嵌入用「字元出現次數」當向量（字越像、相似度越高），生成直接回固定格式。"""
    fail_embed = False  # 類別屬性：設成 True 時嵌入會失敗，用來模擬模型服務掛掉

    def __init__(self, *args, **kwargs):
        """接受任何參數：程式裡用 LLMService(位址, 模型…) 建立，換成假的也要能照樣建立。"""
        pass

    def embed(self, text):
        """把每個字元丟進 ord(字元) % 1024 這一格並計數，得到 1024 維向量。"""
        if FakeLLM.fail_embed:
            from app.core.llm_service import LLMUnavailableError
            raise LLMUnavailableError("down")
        v = [0.0] * EMBEDDING_DIM
        for ch in text:
            v[ord(ch) % EMBEDDING_DIM] += 1.0
        return v

    def generate(self, prompt):
        """不管 prompt 是什麼都回同一句話；測的是流程，不是回答品質。"""
        return "依據參考資料：廢溶劑暫存不得超過九十天。"


# ───────────────────────── 共用的 fixture 與小工具 ─────────────────────────

@pytest.fixture
def client(db, monkeypatch, tmp_path):
    """TestClient 接上測試用 session；背景工作也用同一個 session，上傳檔存到暫存資料夾。"""
    @contextmanager
    def same_session():
        """取代 ingestion.session_scope：背景工作不另開連線，直接用測試的 session（結束時才會 rollback）。"""
        yield db

    # ── 替換外部依賴：monkeypatch 改的東西在測試結束後會自動還原 ──
    FakeLLM.fail_embed = False
    monkeypatch.setattr(ingestion, "session_scope", same_session)
    monkeypatch.setattr(ingestion, "LLMService", FakeLLM)
    monkeypatch.setattr(rag, "LLMService", FakeLLM)
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))  # tmp_path：pytest 給的暫存資料夾

    # ── 覆寫依賴：所有路由的 Depends(get_db) 改拿測試的 session ──
    app.dependency_overrides[get_db] = lambda: db
    # 不用 with TestClient(...)：那樣會觸發啟動事件，去連正式的資料庫
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def depts(db):
    """三個測試部門：運營、業務、資訊；回傳 {代碼: 部門物件}。"""
    rows = {code: Department(code=code, name=name) for code, name in [("ops", "運營"), ("sales", "業務"), ("it", "資訊")]}
    db.add_all(rows.values())
    db.flush()  # flush：送出 INSERT 取得 id，但還沒 commit
    return rows


def make_user(db, depts, email, dept="ops", role="employee"):
    """直接在資料庫建立使用者（略過註冊 API），用來快速準備測試資料。"""
    user = User(email=email, password_hash=hashPassword(PASSWORD), dept_id=depts[dept].id, role=role)
    db.add(user)
    db.flush()
    return user


def login(client, email):
    """登入並回傳帶好 Authorization 標頭的 dict；refresh cookie 留在 client 的 cookie jar 裡。"""
    r = client.post("/api/v1/auth/token", data={"grant_type": "password", "username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(client, headers, *, content=SOP, title="廢棄物處理SOP", level="public", dept="ops", version="v1", filename="sop.txt"):
    """用 multipart/form-data 上傳一份文件（和前端的上傳表單一樣的格式）。"""
    return client.post(
        "/api/v1/documents",
        headers=headers,
        data={"title": title, "dept_code": dept, "level": level, "version": version, "effective_date": ""},
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
    )


@pytest.fixture
def admin(client, db, depts):
    """已登入的 IT 管理員；回傳他的 Authorization 標頭。"""
    make_user(db, depts, "admin@company.com", dept="it", role="it_admin")
    return login(client, "admin@company.com")


@pytest.fixture
def employee(client, db, depts):
    """已登入的運營部員工；回傳他的 Authorization 標頭。"""
    make_user(db, depts, "emp@company.com", dept="ops")
    return login(client, "emp@company.com")


def actions(db):
    """依時間順序列出所有稽核事件名稱，用來斷言「哪些動作有被記錄」。"""
    return [row.action for row in db.scalars(select(AuditLog).order_by(AuditLog.id))]


# ───────────────────────── 註冊與登入 ─────────────────────────

def test_register_ignores_role_and_returns_201(client, db, depts):
    """註冊時自己帶 role=it_admin 也無效，一律是 employee；回應不含密碼雜湊。"""
    r = client.post("/api/v1/users", json={"email": "new@company.com", "password": PASSWORD, "dept_code": "ops", "role": "it_admin"})
    assert r.status_code == 201
    assert r.json()["role"] == "employee"  # 自己填 it_admin 也沒用
    assert "password_hash" not in r.json()


@pytest.mark.parametrize(  # 同一個測試用四組資料各跑一次
    "body,code",
    [
        ({"email": "dup@company.com", "password": PASSWORD, "dept_code": "ops"}, 409),  # email 重複
        ({"email": "x@company.com", "password": PASSWORD, "dept_code": "nope"}, 422),  # 部門不存在
        ({"email": "x@company.com", "password": "short", "dept_code": "ops"}, 422),  # 密碼太短
        ({"email": "not-an-email", "password": PASSWORD, "dept_code": "ops"}, 422),
    ],
)
def test_register_errors_use_unified_format(client, db, depts, body, code):
    """各種註冊錯誤回對的狀態碼，而且錯誤內容都有 code 與 message。"""
    make_user(db, depts, "dup@company.com")
    r = client.post("/api/v1/users", json=body)
    assert r.status_code == code
    assert set(r.json()) >= {"code", "message"}  # 前端讀 message 顯示


def test_login_sets_httponly_refresh_cookie_and_audits(client, db, depts):
    """登入成功：回 access token、設定 HttpOnly 的 refresh cookie、資料庫只存雜湊、寫稽核。"""
    make_user(db, depts, "a@company.com")
    r = client.post("/api/v1/auth/token", data={"grant_type": "password", "username": "a@company.com", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    cookie_header = r.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie_header and "httponly" in cookie_header and "path=/api/v1/auth" in cookie_header
    stored = db.scalar(select(RefreshToken))
    assert stored.token_hash not in r.headers["set-cookie"]  # 資料庫只存雜湊
    assert actions(db) == ["login.success"]


def test_wrong_password_and_unknown_email_get_same_message(client, db, depts):
    """密碼錯與帳號不存在回同一句話（不洩漏帳號是否存在），兩次失敗都有記錄。"""
    make_user(db, depts, "a@company.com")
    bad_pw = client.post("/api/v1/auth/token", data={"grant_type": "password", "username": "a@company.com", "password": "wrong-pass"})
    no_user = client.post("/api/v1/auth/token", data={"grant_type": "password", "username": "ghost@company.com", "password": "wrong-pass"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json()["message"] == no_user.json()["message"]  # 不透露帳號是否存在
    assert actions(db) == ["login.failed", "login.failed"]


def test_me_includes_department(client, employee):
    """/me 回傳的資料帶有部門。"""
    r = client.get("/api/v1/me", headers=employee)
    assert r.status_code == 200
    assert r.json()["department"]["code"] == "ops"


def test_protected_endpoint_without_token_is_401(client):
    """沒帶 token 呼叫需要登入的端點 → 401。"""
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/conversations").status_code == 401


# ───────────────────────── refresh token ─────────────────────────

def refresh(client):
    """用 cookie 裡的 refresh token 續期（和前端 api.refresh() 送的內容一樣）。"""
    return client.post("/api/v1/auth/token", data={"grant_type": "refresh_token"})


def test_refresh_rotates_token(client, db, employee):
    """續期成功後換了一張新 token，舊的被作廢、新的有效。"""
    old_cookie = client.cookies.get("refresh_token")
    r = refresh(client)
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.cookies.get("refresh_token") != old_cookie  # 換了一張新的
    tokens = db.scalars(select(RefreshToken).order_by(RefreshToken.id)).all()
    assert tokens[0].revoked_at is not None and tokens[1].revoked_at is None


def test_reusing_old_refresh_token_revokes_everything(client, db, employee):
    """作廢很久的舊 token 又被拿來用（疑似被偷）→ 這個人所有 token 全部作廢。"""
    old_cookie = client.cookies.get("refresh_token")
    assert refresh(client).status_code == 200
    # 把舊 token 的作廢時間往前推，模擬「作廢很久之後又被拿出來用」（被偷的情境）
    db.execute(update(RefreshToken).where(RefreshToken.revoked_at.is_not(None)).values(revoked_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    client.cookies.set("refresh_token", old_cookie, path="/api/v1/auth")
    assert refresh(client).status_code == 401
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))  # 包含剛換的新 token


def test_reuse_within_grace_period_does_not_revoke_everything(client, db, employee):
    """剛作廢幾秒內的舊 token 再被使用（兩個分頁同時續期）→ 只拒絕，不連坐新 token。"""
    old_cookie = client.cookies.get("refresh_token")
    assert refresh(client).status_code == 200
    client.cookies.set("refresh_token", old_cookie, path="/api/v1/auth")
    assert refresh(client).status_code == 401  # 舊的仍然不能用
    active = [t for t in db.scalars(select(RefreshToken)) if t.revoked_at is None]
    assert len(active) == 1  # 但新的那張沒有被連坐（兩個分頁同時續期的情境）


def test_idle_user_cannot_refresh(client, db, employee):
    """閒置超過設定的分鐘數，refresh 會被拒絕（伺服器端的閒置登出）。"""
    db.execute(update(User).values(last_active_at=datetime.now(timezone.utc) - timedelta(minutes=settings.idle_timeout_minutes + 1)))
    r = refresh(client)
    assert r.status_code == 401
    assert "閒置" in r.json()["message"]


def test_logout_revokes_and_clears_cookie(client, db, employee):
    """登出回 204；之後再用同一張 refresh token 續期會失敗；登出有記錄。"""
    assert client.post("/api/v1/auth/revoke").status_code == 204
    assert refresh(client).status_code == 401
    assert "logout" in actions(db)


# ───────────────────────── 權限（RBAC）─────────────────────────

@pytest.mark.parametrize("method,path", [("get", "/api/v1/documents"), ("get", "/api/v1/users"), ("get", "/api/v1/audit-logs"), ("patch", "/api/v1/users/1")])
def test_admin_endpoints_reject_employee(client, employee, method, path):
    """一般員工呼叫管理員端點 → 403。"""
    kwargs = {"json": {}} if method == "patch" else {}
    # getattr(client, "get") 等同 client.get，用字串決定要呼叫哪個 HTTP 方法
    assert getattr(client, method)(path, headers=employee, **kwargs).status_code == 403


def test_admin_cannot_demote_self(client, db, admin):
    """管理員把自己降級 → 409（避免系統沒有管理員）。"""
    me = client.get("/api/v1/me", headers=admin).json()
    r = client.patch(f"/api/v1/users/{me['id']}", headers=admin, json={"role": "employee"})
    assert r.status_code == 409


def test_deactivating_user_kills_their_refresh_tokens(client, db, depts, admin):
    """停用帳號後，那個人無法再續期，而且他的 token 在資料庫裡都已作廢。"""
    victim = make_user(db, depts, "v@company.com")
    victim_client = TestClient(app)  # 另一個「瀏覽器」：有自己的 cookie jar
    login(victim_client, "v@company.com")
    r = client.patch(f"/api/v1/users/{victim.id}", headers=admin, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert refresh(victim_client).status_code == 401
    # 兩道防線：換 token 時會檢查帳號是否啟用，而 token 本身也已經被作廢（之後重新啟用帳號，舊 token 也不會復活）
    victim_tokens = db.scalars(select(RefreshToken).where(RefreshToken.user_id == victim.id)).all()
    assert victim_tokens and all(t.revoked_at is not None for t in victim_tokens)


# ───────────────────────── 文件入庫 ─────────────────────────

def test_upload_is_accepted_then_processed_in_background(client, db, admin):
    """上傳回 202、狀態 pending；背景工作跑完後變 ready，切出 3 個 chunk。"""
    r = upload(client, admin)
    assert r.status_code == 202
    assert r.json()["status"] == "pending"  # 回應當下還在處理
    doc = db.get(Document, r.json()["id"])
    db.refresh(doc)
    assert doc.status == "ready"  # 背景工作跑完
    assert len(doc.chunks) == 3  # 前言 + 第1條 + 第2條
    assert "document.upload" in actions(db)


def test_duplicate_upload_is_409_and_bad_file_is_422(client, admin):
    """同內容重複上傳 → 409；不支援的副檔名、空檔 → 422。"""
    assert upload(client, admin).status_code == 202
    assert upload(client, admin, version="v9").status_code == 409  # 內容一樣，版本號不同也算重複
    assert upload(client, admin, filename="sop.pdf").status_code == 422
    assert upload(client, admin, content="   ").status_code == 422


def test_failed_processing_can_be_reprocessed(client, db, admin):
    """模型掛掉時文件變 failed；模型恢復後重新處理 → ready；ready 的不能再送處理（409）。"""
    FakeLLM.fail_embed = True
    doc_id = upload(client, admin).json()["id"]
    assert db.get(Document, doc_id).status == "failed"
    FakeLLM.fail_embed = False
    r = client.post(f"/api/v1/documents/{doc_id}/processing-jobs", headers=admin)
    assert r.status_code == 202
    db.expire_all()  # 丟掉 session 裡的快取，下一次讀取會重新查資料庫
    assert db.get(Document, doc_id).status == "ready"
    # ready 的文件不能再送處理
    assert client.post(f"/api/v1/documents/{doc_id}/processing-jobs", headers=admin).status_code == 409


def test_new_version_deprecates_old_one(client, db, admin):
    """同標題上傳新版本：新版 ready、舊版自動 deprecated。"""
    v1 = upload(client, admin).json()["id"]
    v2 = upload(client, admin, content=SOP + "\n第3條 新增條文。", version="v2").json()["id"]
    db.expire_all()
    assert db.get(Document, v1).status == "deprecated"
    assert db.get(Document, v2).status == "ready"


def test_patch_document_cannot_force_ready(client, admin):
    """PATCH 不能把文件手動改成 ready（422），只能改成 deprecated。"""
    doc_id = upload(client, admin).json()["id"]
    assert client.patch(f"/api/v1/documents/{doc_id}", headers=admin, json={"status": "ready"}).status_code == 422
    r = client.patch(f"/api/v1/documents/{doc_id}", headers=admin, json={"status": "deprecated"})
    assert r.status_code == 200 and r.json()["status"] == "deprecated"


def test_list_documents_filters_by_status(client, admin):
    """?status= 篩選有效。"""
    upload(client, admin)
    assert client.get("/api/v1/documents?status=ready", headers=admin).json()["total"] == 1
    assert client.get("/api/v1/documents?status=failed", headers=admin).json()["total"] == 0


# ───────────────────────── 對話與問答 ─────────────────────────

def new_conversation(client, headers):
    """建立一段新對話，回傳它的 UUID。"""
    r = client.post("/api/v1/conversations", headers=headers, json={"title": None})
    assert r.status_code == 201
    return r.json()["id"]


def ask(client, headers, conv_id, content="廢溶劑暫存期限不得超過幾天"):
    """在指定對話裡提問（和前端送出問題一樣）。"""
    return client.post(f"/api/v1/conversations/{conv_id}/messages", headers=headers, json={"content": content})


def test_ask_returns_answer_with_citations_and_preview(client, db, admin, employee):
    """提問成功：回答、出處（含版本與原文）、自動標題、一問一答兩則訊息、稽核紀錄都正確。"""
    upload(client, admin)
    conv_id = new_conversation(client, employee)
    r = ask(client, employee, conv_id)
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "assistant" and body["refused"] is False
    assert body["latency_ms"] is not None
    top = body["citations"][0]
    assert top["rank"] == 1 and top["doc_title"] == "廢棄物處理SOP" and top["version"] == "v1"
    assert top["preview"]  # 有權限，看得到原文
    # 對話標題自動取第一個問題；訊息列表有一問一答
    assert client.get("/api/v1/conversations", headers=employee).json()["items"][0]["title"].startswith("廢溶劑")
    assert [m["role"] for m in client.get(f"/api/v1/conversations/{conv_id}/messages", headers=employee).json()] == ["user", "assistant"]
    assert "ask" in actions(db)


def test_other_department_is_refused_for_dept_level_document(client, db, depts, admin):
    """別的部門的人問「部門限定」文件的內容 → 拒答，而且沒有任何出處。"""
    upload(client, admin, level="dept", dept="ops")
    make_user(db, depts, "sales@company.com", dept="sales")
    sales = login(client, "sales@company.com")
    body = ask(client, sales, new_conversation(client, sales)).json()
    assert body["refused"] is True and body["content"] == REFUSE_TEXT
    assert body["citations"] == []


def test_deprecated_document_is_no_longer_answered(client, admin, employee):
    """文件作廢後，同樣的問題會被拒答。"""
    doc_id = upload(client, admin).json()["id"]
    client.patch(f"/api/v1/documents/{doc_id}", headers=admin, json={"status": "deprecated"})
    assert ask(client, employee, new_conversation(client, employee)).json()["refused"] is True


def test_preview_is_rechecked_when_reading_later(client, admin, employee):
    """回答之後文件改成限閱：再讀那則回答，出處還在，但原文不給看。"""
    doc_id = upload(client, admin).json()["id"]
    conv_id = new_conversation(client, employee)
    ask(client, employee, conv_id)
    # 回答之後文件改成限閱：出處紀錄（標題、條號）還在，但原文不再給看
    client.patch(f"/api/v1/documents/{doc_id}", headers=admin, json={"level": "restricted"})
    citation = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=employee).json()[1]["citations"][0]
    assert citation["doc_title"] == "廢棄物處理SOP"
    assert citation["preview"] is None


def test_cannot_touch_someone_elses_conversation(client, db, depts, admin, employee):
    """別人的對話：讀、提問、按回饋、刪除都是 404，列表裡也看不到。"""
    upload(client, admin)
    conv_id = new_conversation(client, employee)
    answer_id = ask(client, employee, conv_id).json()["id"]
    make_user(db, depts, "other@company.com")
    other = login(client, "other@company.com")
    assert client.get(f"/api/v1/conversations/{conv_id}/messages", headers=other).status_code == 404
    assert ask(client, other, conv_id).status_code == 404
    assert client.put(f"/api/v1/messages/{answer_id}/feedback", headers=other, json={"value": "up"}).status_code == 404
    assert client.delete(f"/api/v1/conversations/{conv_id}", headers=other).status_code == 404
    assert client.get("/api/v1/conversations", headers=other).json()["total"] == 0


def test_feedback_toggles(client, admin, employee):
    """回饋切換：up → down → 再按 down 取消；不合法的值 → 422。"""
    upload(client, admin)
    answer_id = ask(client, employee, new_conversation(client, employee)).json()["id"]
    url = f"/api/v1/messages/{answer_id}/feedback"
    assert client.put(url, headers=employee, json={"value": "up"}).json()["feedback"] == "up"
    assert client.put(url, headers=employee, json={"value": "down"}).json()["feedback"] == "down"
    assert client.put(url, headers=employee, json={"value": "down"}).json()["feedback"] is None  # 再按一次取消
    assert client.put(url, headers=employee, json={"value": "meh"}).status_code == 422


def test_delete_conversation_cascades(client, admin, employee):
    """刪除對話回 204，之後讀它的訊息是 404。"""
    upload(client, admin)
    conv_id = new_conversation(client, employee)
    ask(client, employee, conv_id)
    assert client.delete(f"/api/v1/conversations/{conv_id}", headers=employee).status_code == 204
    assert client.get(f"/api/v1/conversations/{conv_id}/messages", headers=employee).status_code == 404


def test_empty_question_is_422(client, employee):
    """空白問題 → 422，錯誤代碼是 validation_error。"""
    r = ask(client, employee, new_conversation(client, employee), content="")
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


# ───────────────────────── 稽核 ─────────────────────────

def test_audit_log_lists_events_without_question_content(client, db, admin, employee):
    """稽核紀錄可依事件篩選，而且完全不含提問內容。"""
    upload(client, admin)
    ask(client, employee, new_conversation(client, employee), content="機密問題內容XYZ")
    r = client.get("/api/v1/audit-logs?action=ask", headers=admin)
    assert r.status_code == 200 and r.json()["total"] == 1
    assert "XYZ" not in r.text  # 稽核紀錄不含提問內容
    everything = client.get("/api/v1/audit-logs?limit=100", headers=admin).json()
    assert {"login.success", "document.upload", "ask"} <= {item["action"] for item in everything["items"]}
