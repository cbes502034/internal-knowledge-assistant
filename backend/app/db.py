"""資料庫連線。engine 建立時不會真的連線，第一次查詢才連。"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 依賴：每個請求一個 Session，結束時關閉。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
