"""需要資料庫的測試：檢索的權限過濾、排序、融合，以及完整問答流程（模型用假的）。"""
from types import SimpleNamespace

import pytest

from app.core.llm_service import LLMUnavailableError
from app.core.retriever import hybrid_search, keyword_search, vector_search
from app.models.department import Department
from app.models.document import EMBEDDING_DIM, Document, DocumentChunk
from app.models.user import User
from app.services.rag import LLM_DOWN_TEXT, MIN_SIMILARITY, REFUSE_TEXT, answer_question


def vec(*hot):
    """第 hot 維為 1、其餘為 0 的向量；兩個向量的餘弦相似度可以直接心算。"""
    v = [0.0] * EMBEDDING_DIM
    for i in hot:
        v[i] = 1.0
    return v


@pytest.fixture
def world(db):
    """3 個部門、3 位使用者、7 份文件（涵蓋各種等級與狀態），每份一個 chunk。"""
    depts = {code: Department(code=code, name=code) for code in ("sales", "rd", "ops")}
    db.add_all(depts.values())
    db.flush()

    def make_user(email, dept, role):
        u = User(email=email, password_hash="x", dept_id=depts[dept].id, role=role)
        db.add(u)
        db.flush()
        return u

    users = SimpleNamespace(
        sales=make_user("sales@t.test", "sales", "employee"),
        rd=make_user("rd@t.test", "rd", "employee"),
        admin=make_user("admin@t.test", "ops", "it_admin"),
    )

    def make_chunk(title, dept, level, status, article_no, content, hot):
        doc = Document(title=title, dept_id=depts[dept].id, level=level, version="v1", status=status)
        db.add(doc)
        db.flush()
        chunk = DocumentChunk(document_id=doc.id, chunk_index=0, article_no=article_no, content=content, embedding=vec(hot))
        db.add(chunk)
        db.flush()
        return chunk

    chunks = SimpleNamespace(
        c1=make_chunk("廢棄物處理SOP", "ops", "public", "ready", "第1條", "第1條 廢溶劑暫存期限不得超過九十天。", 0),
        c2=make_chunk("廢棄物容器規範", "ops", "public", "ready", "第2條", "第2條 廢溶劑容器應標示內容物與日期。", 1),
        c3=make_chunk("業務差旅辦法", "sales", "dept", "ready", "第1條", "第1條 出差住宿費每晚上限三千元。", 2),
        c4=make_chunk("研發機密規範", "rd", "dept", "ready", "第1條", "第1條 研發原始碼不得外流。", 3),
        c5=make_chunk("資安事件通報程序", "ops", "restricted", "ready", "第1條", "第1條 資安事件須於一小時內通報。", 4),
        c6=make_chunk("舊版巡檢表", "ops", "public", "deprecated", "第1條", "第1條 舊版巡檢頻率為每月一次。", 5),
        c7=make_chunk("審核中草案", "ops", "public", "pending", "第1條", "第1條 待審核的草案內容。", 6),
    )
    return SimpleNamespace(users=users, chunks=chunks)


VISIBLE = [
    ("sales", {"c1", "c2", "c3"}),  # public + 自己部門的 dept
    ("rd", {"c1", "c2", "c4"}),
    ("admin", {"c1", "c2", "c5"}),  # public + restricted；別的部門的 dept 文件看不到
]
# c6（已作廢）與 c7（尚未處理完）任何人都不該看到


def ids(world, names):
    return {getattr(world.chunks, name).id for name in names}


# ───────────────────────── 權限過濾 ─────────────────────────

@pytest.mark.parametrize("who,expected", VISIBLE)
def test_vector_search_only_returns_visible_chunks(db, world, who, expected):
    hits = vector_search(db, vec(0, 1, 2, 3, 4, 5, 6), getattr(world.users, who), k=50)
    assert {h.chunk_id for h in hits} == ids(world, expected)


@pytest.mark.parametrize("who,expected", VISIBLE)
def test_keyword_search_only_returns_visible_chunks(db, world, who, expected):
    # 「第1條 第2條」會命中所有 chunk 的標題，所以沒出現的唯一原因只能是權限或狀態
    hits = keyword_search(db, "第1條 第2條", getattr(world.users, who), k=50)
    assert {h.chunk_id for h in hits} == ids(world, expected)


@pytest.mark.parametrize("who,expected", VISIBLE)
def test_hybrid_search_only_returns_visible_chunks(db, world, who, expected):
    hits = hybrid_search(db, "第1條 第2條", vec(0, 1, 2, 3, 4, 5, 6), getattr(world.users, who), k=50)
    assert {h.chunk_id for h in hits} == ids(world, expected)


def test_hybrid_does_not_leak_other_departments_chunk_even_when_it_matches_best(db, world):
    # 業務部的人用「研發部機密」的向量與關鍵字去查，仍然看不到它
    hits = hybrid_search(db, "研發原始碼不得外流", vec(3), world.users.sales, k=10)
    assert world.chunks.c4.id not in {h.chunk_id for h in hits}


# ───────────────────────── 排序與分數 ─────────────────────────

def test_vector_search_order_and_similarity(db, world):
    hits = vector_search(db, vec(0), world.users.sales, k=3)
    assert hits[0].chunk_id == world.chunks.c1.id
    assert hits[0].similarity == pytest.approx(1.0)
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].similarity == pytest.approx(0.0, abs=1e-6)
    assert [h.chunk_id for h in hits[1:]] == [world.chunks.c2.id, world.chunks.c3.id]  # 同分時依編號，結果可重現


def test_vector_search_partial_similarity_and_limit(db, world):
    hits = vector_search(db, vec(0, 1), world.users.sales, k=1)
    assert len(hits) == 1
    assert hits[0].similarity == pytest.approx(0.5 ** 0.5)  # 兩個單位向量夾 45 度


def test_keyword_search_ranks_exact_matches_first(db, world):
    hits = keyword_search(db, "廢溶劑暫存期限", world.users.sales, k=10)
    assert hits[0].chunk_id == world.chunks.c1.id
    assert world.chunks.c3.id not in {h.chunk_id for h in hits}  # 完全不相關的不該出現
    assert all(h.similarity is None for h in hits)


def test_keyword_search_matches_document_title(db, world):
    hits = keyword_search(db, "差旅辦法", world.users.sales, k=10)
    assert [h.chunk_id for h in hits] == [world.chunks.c3.id]


def test_keyword_search_with_no_visible_chunks(db):
    dept = Department(code="x", name="x")
    db.add(dept)
    db.flush()
    user = User(email="nobody@t.test", password_hash="x", dept_id=dept.id, role="employee")
    db.add(user)
    db.flush()
    assert keyword_search(db, "任何查詢", user) == []
    assert vector_search(db, vec(0), user) == []


def test_hybrid_fuses_and_deduplicates(db, world):
    hits = hybrid_search(db, "廢溶劑暫存期限", vec(0), world.users.sales, k=5)
    chunk_ids = [h.chunk_id for h in hits]
    assert chunk_ids[0] == world.chunks.c1.id
    assert len(chunk_ids) == len(set(chunk_ids))  # 兩路都找到的 chunk 只出現一次
    assert hits[0].score == pytest.approx(2 / 61)  # 兩路都排第一
    assert hits[0].similarity == pytest.approx(1.0)  # 保留了向量那一路的相似度，拒答判斷要用
    assert len(hybrid_search(db, "廢溶劑", vec(0), world.users.sales, k=2)) == 2


# ───────────────────────── 完整問答流程（模型用假的）─────────────────────────

class FakeLLM:
    def __init__(self, embedding, answer="根據[廢棄物處理SOP 第1條]，不得超過九十天。", down_on=None):
        self.embedding = embedding
        self.answer = answer
        self.down_on = down_on
        self.prompts = []

    def embed(self, text):
        if self.down_on == "embed":
            raise LLMUnavailableError("down")
        return self.embedding

    def generate(self, prompt):
        if self.down_on == "generate":
            raise LLMUnavailableError("down")
        self.prompts.append(prompt)
        return self.answer


def test_answer_question_happy_path(db, world):
    llm = FakeLLM(vec(0))
    result = answer_question(db, world.users.sales, "廢溶劑暫存期限是多久", llm)
    assert result["answer"] == llm.answer
    assert result["citations"][0].chunk_id == world.chunks.c1.id
    prompt = llm.prompts[0]
    assert "廢溶劑暫存期限不得超過九十天" in prompt  # 檢索到的內容有放進 prompt
    assert "廢溶劑暫存期限是多久" in prompt  # 問題也有
    assert "[廢棄物處理SOP 第1條]" in prompt  # 標了出處，模型才引用得到


def test_answer_question_never_shows_unauthorised_content_to_the_model(db, world):
    llm = FakeLLM(vec(0, 3, 4))  # 向量同時貼近 c1、c4（研發機密）、c5（資安受限）
    answer_question(db, world.users.sales, "研發原始碼 資安事件 廢溶劑", llm)
    prompt = llm.prompts[0]
    assert "研發原始碼不得外流" not in prompt
    assert "資安事件須於一小時內通報" not in prompt


def test_answer_question_citations_are_exactly_what_the_model_saw(db, world, monkeypatch):
    from app.services import rag

    monkeypatch.setattr(rag, "fit_hits", lambda hits: hits[:1])  # 模擬字數上限，只放得下第一筆
    llm = FakeLLM(vec(0, 1))  # c1、c2 都很相近，檢索會回傳兩筆以上
    result = answer_question(db, world.users.sales, "廢溶劑", llm)

    assert len(result["citations"]) == 1
    shown = result["citations"][0]
    other = world.chunks.c2 if shown.chunk_id == world.chunks.c1.id else world.chunks.c1
    assert shown.content in llm.prompts[0]
    assert other.content not in llm.prompts[0]  # 沒放進 prompt 的，就不能出現在出處清單裡


def test_answer_question_refuses_without_calling_the_model_when_nothing_similar(db, world):
    llm = FakeLLM(vec(100))  # 與所有 chunk 都正交（相似度 0）
    result = answer_question(db, world.users.sales, "員工旅遊補助", llm)
    assert result == {"answer": REFUSE_TEXT, "citations": []}
    assert llm.prompts == []  # 拒答時不該浪費一次生成


def test_answer_question_threshold_boundary(db, world):
    above = vec(0, 10)  # 與 c1 的相似度 0.707 > 門檻
    below = vec(0, 10, 11, 12)  # 與 c1 的相似度 0.5 < 門檻
    assert 0.5 < MIN_SIMILARITY < 0.707
    assert answer_question(db, world.users.sales, "q", FakeLLM(above))["answer"] != REFUSE_TEXT
    assert answer_question(db, world.users.sales, "q", FakeLLM(below))["answer"] == REFUSE_TEXT


def test_answer_question_refuses_when_nothing_is_visible(db):
    dept = Department(code="y", name="y")
    db.add(dept)
    db.flush()
    user = User(email="nobody2@t.test", password_hash="x", dept_id=dept.id, role="employee")
    db.add(user)
    db.flush()
    assert answer_question(db, user, "q", FakeLLM(vec(0)))["answer"] == REFUSE_TEXT


@pytest.mark.parametrize("down_on", ["embed", "generate"])
def test_answer_question_degrades_gracefully_when_model_is_down(db, world, down_on):
    result = answer_question(db, world.users.sales, "廢溶劑暫存期限", FakeLLM(vec(0), down_on=down_on))
    assert result == {"answer": LLM_DOWN_TEXT, "citations": []}
