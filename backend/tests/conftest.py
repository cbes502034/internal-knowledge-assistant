"""共用測試設定：臨時資料庫，與每個測試各自獨立、結束即 rollback 的 session。"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  確保所有 model 都已登記進 Base.metadata
from app.core.database import DATABASE_URL, Base

TEST_DB = "ika_pytest_tmp"


@pytest.fixture(scope="session")
def test_engine():
    """建立專用的臨時資料庫，測完就刪掉；不會碰你平常使用的資料庫。"""
    admin = create_engine(DATABASE_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    except OperationalError:
        admin.dispose()
        pytest.skip("連不上資料庫（請先 docker compose up -d），略過資料庫測試")

    engine = create_engine(DATABASE_URL.set(database=TEST_DB))
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture
def db(test_engine):
    """每個測試一個 session；結束時整包 rollback，測試之間不會互相污染。"""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()
