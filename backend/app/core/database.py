from typing import Generator
from app.core.config import settings

from sqlalchemy.orm import  (
    DeclarativeBase,
    sessionmaker,
    Session
)

from sqlalchemy import URL, create_engine

DATABASE_URL = URL.create(
    drivername="postgresql+psycopg",
    username=settings.postgres_user,
    password=settings.postgres_password,
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_database
)



engine = create_engine(
    DATABASE_URL,
    echo=True,          # 設為 True 會在終端機印出 SQL 語句，正式環境建議改為 False
    pool_size=5,        # 連線池維持的常駐連線數
    max_overflow=10,    # 超過 pool_size 時允許額外建立的最大連線數
    pool_pre_ping=True  # 每次取用連線前先測試是否存活，避免資料庫斷線報錯
)

SessionLocal = sessionmaker(
    autoflush=False,
    autocommit=False,
    bind=engine
)

class Base(DeclarativeBase):
    pass

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

