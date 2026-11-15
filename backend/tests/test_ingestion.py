"""
【檔案用途】單元 2 入庫流程的測試（直接呼叫服務層，不經過 API；API 在單元 3 才接上）。
模型用假的（FakeEmbedder），所以不需要 Ollama；資料庫用臨時測試庫。

驗證的重點：
  1. 第一段 register_upload：格式檢查、checksum 擋重複、建立 pending 主檔
  2. 第二段 process_document：切塊寫入、改成 ready
  3. 失敗時：標成 failed、不留下半成品 chunk、可以重新處理
  4. 新版本上線：舊版作廢；新版失敗時舊版不受影響
"""
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.llm_service import LLMUnavailableError
from app.core.retriever import vector_search
from app.models.department import Department
from app.models.document import EMBEDDING_DIM, Document, DocumentChunk
from app.models.user import User
from app.services.ingestion import (
    DuplicateDocumentError,
    InvalidUploadError,
    compute_checksum,
    decode_text,
    deprecate_document,
    mark_interrupted_as_failed,
    process_document,
    register_upload,
)

SOP = "廢棄物處理SOP\n第1條 廢溶劑暫存期限不得超過九十天。\n第2條 容器應標示內容物與日期。"


class FakeEmbedder:
    """假的嵌入模型：每次回傳不同的單位向量；fail_on=N 代表第 N 次呼叫時模型「掛掉」。"""

    def __init__(self, fail_on=None):
        self.calls = []  # 記錄被要求嵌入的文字，用來檢查呼叫次數
        self.fail_on = fail_on

    def embed(self, text):
        self.calls.append(text)
        if self.fail_on == len(self.calls):
            raise LLMUnavailableError("down")
        v = [0.0] * EMBEDDING_DIM
        v[len(self.calls) - 1] = 1.0  # 第 1 次回傳第 0 維為 1 的向量，第 2 次第 1 維…
        return v


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    """上傳的原始檔存到 pytest 的暫存資料夾，測完自動清掉，不會在專案裡留下檔案。"""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


@pytest.fixture
def dept(db):
    d = Department(code="ops", name="營運")
    db.add(d)
    db.flush()
    return d


def upload(db, dept, content=SOP, filename="sop.txt", **overrides):
    """第一段：受理上傳，回傳 pending 的文件。"""
    kwargs = dict(dept_id=dept.id, title="廢棄物處理SOP", version="v1", level="public")
    kwargs.update(overrides)
    return register_upload(db, filename=filename, raw=content.encode("utf-8"), **kwargs)


def ingest(db, dept, llm=None, **kwargs):
    """兩段一起跑：受理上傳 + 背景處理。"""
    document = upload(db, dept, **kwargs)
    return process_document(db, document.id, llm=llm or FakeEmbedder())


def chunk_count(db, document_id):
    return db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id))


# ───────────────────────── 純函式 ─────────────────────────

def test_checksum_depends_only_on_content():
    assert compute_checksum(b"abc") == compute_checksum(b"abc")
    assert compute_checksum(b"abc") != compute_checksum(b"abd")  # 差一個字就完全不同
    assert len(compute_checksum(b"abc")) == 64


def test_decode_text_strips_bom_and_rejects_bad_input():
    assert decode_text("﻿你好".encode("utf-8")) == "你好"  # 記事本存檔的 BOM 會被去掉
    with pytest.raises(InvalidUploadError):
        decode_text(b"  \n ")  # 只有空白
    with pytest.raises(InvalidUploadError):
        decode_text("你好".encode("big5"))  # 不是 UTF-8


# ───────────────────────── 第一段：受理上傳 ─────────────────────────

def test_register_creates_pending_document_without_chunks(db, dept):
    doc = upload(db, dept)
    assert doc.status == "pending"  # 還沒處理，不會被檢索到
    assert doc.checksum == compute_checksum(SOP.encode("utf-8"))
    assert doc.source == "sop.txt"  # 沒填來源就用檔名
    assert chunk_count(db, doc.id) == 0


@pytest.mark.parametrize(
    "filename,content",
    [("sop.pdf", SOP), ("sop.txt", "   "), ("big.txt", "字" * (2 * 1024 * 1024))],  # 格式、空檔、超過 5 MB
)
def test_register_rejects_invalid_files(db, dept, filename, content):
    with pytest.raises(InvalidUploadError):
        upload(db, dept, content=content, filename=filename)
    assert db.scalar(select(Document)) is None  # 驗證失敗時資料庫完全沒被動到


def test_duplicate_content_is_rejected_even_with_new_version(db, dept):
    first = upload(db, dept)
    with pytest.raises(DuplicateDocumentError) as err:
        upload(db, dept, version="v2", filename="改名.txt")  # 換版本號、換檔名，內容一樣照樣擋
    assert err.value.existing_id == first.id


def test_same_content_in_another_department_is_allowed(db, dept):
    other = Department(code="rd", name="研發")
    db.add(other)
    db.flush()
    upload(db, dept)
    assert upload(db, other).status == "pending"


# ───────────────────────── 第二段：處理 ─────────────────────────

def test_process_writes_one_chunk_per_article_and_marks_ready(db, dept):
    llm = FakeEmbedder()
    doc = ingest(db, dept, llm=llm)

    assert doc.status == "ready"
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index)).all()
    assert [c.article_no for c in chunks] == ["前言", "第1條", "第2條"]
    assert len(llm.calls) == 3  # 每個 chunk 嵌入一次
    assert llm.calls[1] == chunks[1].content  # 嵌入的就是 chunk 內文


def test_processed_document_is_searchable(db, dept):
    ingest(db, dept)
    user = User(email="u@company.com", password_hash="x", dept_id=dept.id, role="employee")
    db.add(user)
    db.flush()
    query = [0.0] * EMBEDDING_DIM
    query[1] = 1.0  # 對應第 2 次嵌入，也就是「第1條」
    hits = vector_search(db, query, user, k=3)
    assert (hits[0].doc_title, hits[0].article_no) == ("廢棄物處理SOP", "第1條")


def test_failed_embedding_marks_failed_and_leaves_no_chunks(db, dept):
    doc = upload(db, dept)
    with pytest.raises(LLMUnavailableError):
        process_document(db, doc.id, llm=FakeEmbedder(fail_on=2))  # 第 2 塊嵌入時模型掛掉

    db.expire_all()
    assert db.get(Document, doc.id).status == "failed"  # 留下紀錄，管理員看得到
    assert chunk_count(db, doc.id) == 0  # 第 1 塊雖然嵌入成功，也不能留下（沒有半成品）


def test_failed_document_can_be_reprocessed_or_reuploaded(db, dept):
    doc = upload(db, dept)
    with pytest.raises(LLMUnavailableError):
        process_document(db, doc.id, llm=FakeEmbedder(fail_on=1))
    assert upload(db, dept).status == "pending"  # failed 的同內容檔案不算重複，可以重新上傳
    assert process_document(db, doc.id, llm=FakeEmbedder()).status == "ready"  # 原本那份也能重新處理


# ───────────────────────── 新版本取代舊版本 ─────────────────────────

def test_new_version_deprecates_old_version(db, dept):
    v1 = ingest(db, dept, version="v1")
    v2 = ingest(db, dept, content=SOP + "\n第3條 新增條文。", version="v2")
    db.expire_all()
    assert db.get(Document, v1.id).status == "deprecated"
    assert db.get(Document, v2.id).status == "ready"


def test_other_title_is_not_deprecated(db, dept):
    a = ingest(db, dept, title="文件A")
    ingest(db, dept, content="另一份文件", title="文件B")
    db.expire_all()
    assert db.get(Document, a.id).status == "ready"


def test_failed_new_version_keeps_old_version_ready(db, dept):
    v1 = ingest(db, dept, version="v1")
    v2 = upload(db, dept, content=SOP + "\n第3條 新增條文。", version="v2")
    with pytest.raises(LLMUnavailableError):
        process_document(db, v2.id, llm=FakeEmbedder(fail_on=1))
    db.expire_all()
    assert db.get(Document, v1.id).status == "ready"  # 新版沒成功，舊版不能先被作廢，否則知識庫出現空窗


# ───────────────────────── 其他 ─────────────────────────

def test_restart_marks_stuck_pending_as_failed(db, dept):
    doc = upload(db, dept)  # 模擬：上傳後、背景還沒處理完，伺服器就重啟了
    assert mark_interrupted_as_failed(db) == 1
    db.expire_all()
    assert db.get(Document, doc.id).status == "failed"


def test_deprecate_document(db, dept):
    doc = ingest(db, dept)
    assert deprecate_document(db, doc).status == "deprecated"
