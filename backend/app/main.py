from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status
)
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.errors import register_error_handlers

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.routers import audit, auth, conversations, departments, documents, users
from app.services.ingestion import mark_interrupted_as_failed


@asynccontextmanager
async def lifespan(app: FastAPI):
    """伺服器啟動時執行一次：上次關機時還在處理的文件標成 failed，管理員才能重新處理。"""
    with SessionLocal() as db:
        mark_interrupted_as_failed(db)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# CORS：前端（127.0.0.1:5500）和 API（127.0.0.1:7999）埠號不同，瀏覽器視為不同來源，
# 預設會擋下跨來源請求；這裡明確列出允許的前端網址。
# allow_credentials=True 才能帶 refresh token 的 cookie，而這時 allow_origins 不能用 "*"（規格禁止）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

register_error_handlers(app)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(departments.router)
app.include_router(documents.router)
app.include_router(conversations.router)
app.include_router(audit.router)


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
