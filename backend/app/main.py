from contextlib import asynccontextmanager  # 【單元 2】把 async 產生器變成 lifespan 可用的情境管理器

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status
)
from app.core.config import settings
from app.core.database import SessionLocal, get_db  # 【單元 2】SessionLocal：啟動時自己開 session

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.routers import auth, users
from app.services.ingestion import mark_interrupted_as_failed  # 【單元 2】啟動時清理卡在 pending 的文件


# 【單元 2】生命週期：yield 之前的程式在伺服器啟動時跑一次，yield 之後的在關閉時跑
@asynccontextmanager
async def lifespan(app: FastAPI):
    """伺服器啟動時執行一次：上次關機時還在處理的文件標成 failed，管理員才能重新處理。"""
    with SessionLocal() as db:
        mark_interrupted_as_failed(db)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)


@app.get("/")
def test():
    return {"ok":True}

@app.get("/health")
def health():
    return {"ok":"health"}

@app.get("/get-db")
def test_db(db : Session = Depends(get_db)):
    try:
        result = db.execute(text("SELECT NOW()")).scalar()
        return {
            "status" : "success",
            "message" : f"{settings.postgres_database} 資料庫連線正常",
            "db_time" : result
        }
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"資料庫連線失敗：{str(e)}",
        )
