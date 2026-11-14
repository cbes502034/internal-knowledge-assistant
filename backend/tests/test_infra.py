"""骨架本身的測試：現在就應該全部通過（不需要資料庫與模型）。"""

EXPECTED_ROUTES = {
    ("POST", "/api/v1/auth/token"), ("POST", "/api/v1/auth/revoke"),
    ("POST", "/api/v1/users"), ("GET", "/api/v1/users"), ("PATCH", "/api/v1/users/{user_id}"),
    ("GET", "/api/v1/me"), ("GET", "/api/v1/departments"),
    ("POST", "/api/v1/conversations"), ("GET", "/api/v1/conversations"),
    ("DELETE", "/api/v1/conversations/{conversation_id}"),
    ("GET", "/api/v1/conversations/{conversation_id}/messages"),
    ("POST", "/api/v1/conversations/{conversation_id}/messages"),
    ("PUT", "/api/v1/messages/{message_id}/feedback"),
    ("GET", "/api/v1/documents"), ("POST", "/api/v1/documents"),
    ("GET", "/api/v1/documents/{document_id}"), ("PATCH", "/api/v1/documents/{document_id}"),
    ("POST", "/api/v1/documents/{document_id}/processing-jobs"),
    ("POST", "/api/v1/eval-runs"), ("GET", "/api/v1/eval-runs"),
    ("GET", "/api/v1/eval-runs/{run_id}/results"),
    ("GET", "/api/v1/audit-logs"),
}


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_all_planned_endpoints_are_registered(client):
    spec = client.get("/api/v1/openapi.json").json()
    actual = {(method.upper(), path) for path, ops in spec["paths"].items() for method in ops}
    assert EXPECTED_ROUTES <= actual, f"缺少端點：{EXPECTED_ROUTES - actual}"


def test_protected_endpoint_without_token_returns_401_in_unified_format(client):
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"
    assert "message" in r.json()


def test_validation_error_uses_unified_format(client):
    r = client.post("/api/v1/users", json={"email": "not-an-email", "password": "x", "dept_code": "ops"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert {f["field"] for f in body["fields"]} == {"email", "password"}


def test_unimplemented_logic_returns_501_and_names_the_function(client):
    r = client.post("/api/v1/users",
                    json={"email": "a@example.com", "password": "long-enough-pw", "dept_code": "ops"})
    assert r.status_code == 501
    assert r.json()["code"] == "not_implemented"
    assert "register_user" in r.json()["message"]
