"""文件上傳、背景處理、冪等的重新處理、作廢。"""
import pytest

from tests.fakes import make_user

pytestmark = pytest.mark.db

SOP = "測試SOP\n第1條 甲規定。\n第2條 乙規定。\n第2-1條 乙之一規定。\n第3條 （刪除）\n"


def upload(client, headers, data: bytes = SOP.encode(), filename="sop.txt", title="測試SOP", **form):
    fields = {"title": title, "dept_code": "ops", "level": "public", "version": "v1", **form}
    return client.post("/api/v1/documents", data=fields, files={"file": (filename, data, "text/plain")},
                       headers=headers)


@pytest.fixture
def admin(client):
    return make_user(client, "it@example.com", dept="gm_office", role="it_admin")


def test_upload_is_processed_in_background(client, admin, fake_llm):
    r = upload(client, admin)
    assert r.status_code == 202 and r.json()["status"] == "pending"
    detail = client.get(f"/api/v1/documents/{r.json()['id']}", headers=admin).json()
    assert detail["status"] == "ready" and detail["chunk_mode"] == "article"
    assert detail["chunk_count"] == 3                        # 第1、2、2-1條；已刪除的第3條略過
    assert fake_llm.embedded == 3


def test_reprocess_is_idempotent_and_reuses_vectors(client, admin, fake_llm):
    document_id = upload(client, admin).json()["id"]
    before = fake_llm.embedded
    r = client.post(f"/api/v1/documents/{document_id}/processing-jobs", headers=admin)
    assert r.status_code == 202
    detail = client.get(f"/api/v1/documents/{document_id}", headers=admin).json()
    assert detail["status"] == "ready" and detail["chunk_count"] == 3
    assert fake_llm.embedded == before                      # 內容沒變，不重算向量


def test_document_without_article_numbers_uses_sliding_window(client, admin):
    text = ("這是一份沒有條號的說明文件。" * 60).encode()
    document_id = upload(client, admin, data=text, filename="guide.md", title="說明文件").json()["id"]
    detail = client.get(f"/api/v1/documents/{document_id}", headers=admin).json()
    assert detail["chunk_mode"] == "window" and detail["chunk_count"] >= 2


def test_processing_failure_marks_document_failed(client, admin, fake_llm):
    fake_llm.down = True
    document_id = upload(client, admin).json()["id"]
    detail = client.get(f"/api/v1/documents/{document_id}", headers=admin).json()
    assert detail["status"] == "failed" and detail["chunk_count"] == 0


def test_deprecated_document_is_not_searchable_and_cannot_be_reprocessed(client, admin):
    document_id = upload(client, admin).json()["id"]
    assert client.patch(f"/api/v1/documents/{document_id}", json={"status": "deprecated"},
                        headers=admin).json()["status"] == "deprecated"
    r = client.post(f"/api/v1/documents/{document_id}/processing-jobs", headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "document_deprecated"

    user = make_user(client, "ops@example.com", dept="ops")
    conversation = client.post("/api/v1/conversations", json={}, headers=user).json()
    reply = client.post(f"/api/v1/conversations/{conversation['id']}/messages",
                        json={"content": "甲規定是什麼"}, headers=user).json()
    assert all(c["doc_title"] != "測試SOP" for c in reply["citations"])


def test_upload_validation(client, admin):
    assert upload(client, admin).status_code == 202
    assert upload(client, admin).json()["code"] == "duplicate_document"
    assert upload(client, admin, data=b"x", filename="a.exe", title="X").json()["code"] == "unsupported_file_type"
    assert upload(client, admin, data=b"other", title="Y", dept_code="nope").json()["code"] == "unknown_department"


def test_only_it_admin_manages_documents(client):
    user = make_user(client, "ops@example.com", dept="ops")
    assert upload(client, user).status_code == 403
    assert client.get("/api/v1/documents", headers=user).status_code == 403
