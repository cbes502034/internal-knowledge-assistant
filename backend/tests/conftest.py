"""測試共用設定。

- spec／infra 測試不需要資料庫，也不需要模型。
- 標記 @pytest.mark.db 的測試：使用獨立的測試資料庫（原資料庫名稱加上 _test），
  第一次自動建立並套用遷移；每個測試開始前清空資料、模型換成假的（FakeLLM）。
  執行：pytest -m db（需要先 docker compose up -d db）
"""
import os
import tempfile
from pathlib import Path

# ---- 必須在 import app 之前設定：app.db 在 import 時就依設定建立連線物件 ----
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("SCORE_THRESHOLD", "0.1")          # 假模型的向量分布和真模型不同
os.environ.setdefault("RATE_LIMIT_PER_MIN", "1000")
os.environ.setdefault("UPLOAD_DIR", tempfile.mkdtemp(prefix="ika-uploads-"))

from app.config import get_settings  # noqa: E402


def _test_database_url(url: str) -> str:
    base, _, name = url.rpartition("/")
    return url if name.endswith("_test") else f"{base}/{name}_test"


os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or _test_database_url(get_settings().database_url)
get_settings.cache_clear()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.main import create_app  # noqa: E402
from tests.fakes import FakeLLM  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = ("users, refresh_tokens, documents, chunks, conversations, messages, message_citations, "
          "audit_logs, eval_cases, eval_runs, eval_results")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="session")
def database():
    """建立測試資料庫（若不存在）並套用全部遷移、建立部門。"""
    from alembic import command
    from alembic.config import Config

    url = get_settings().database_url
    base, _, name = url.rpartition("/")
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}):
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")

    from scripts import seed
    seed.main()
    yield config


@pytest.fixture
def fake_llm(database):
    """清空資料、重設快取與限流，並把模型換成假的。"""
    from app import deps
    from app.core import retriever
    from app.core.llm_service import set_llm
    from app.db import engine

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    retriever.clear_caches()
    deps._ask_limiter.cache_clear()
    fake = FakeLLM()
    set_llm(fake)
    yield fake
    set_llm(None)


@pytest.fixture(autouse=True)
def _prepare_db_tests(request):
    if request.node.get_closest_marker("db"):
        request.getfixturevalue("fake_llm")
