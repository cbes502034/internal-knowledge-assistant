"""
【檔案用途】FastAPI 應用程式的進入點：建立 app、掛上中介層（CORS）、錯誤處理與所有路由。
啟動方式（在 backend 目錄）：.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 7999
  app.main:app 的意思是「app/main.py 這個模組裡，名叫 app 的物件」。

一個請求進來的順序：
  CORS 中介層 → 路由比對 → 依賴注入（get_db、get_current_user…）→ 路由函式 → 回應
  途中丟出的 HTTPException／驗證錯誤 → core/errors.py 統一轉成 {"code","message"}
"""

from contextlib import asynccontextmanager  # 把 async 產生器變成 lifespan 可用的情境管理器

from fastapi import (
    FastAPI,  # 應用程式本體
    Depends,  # 依賴注入
    HTTPException,  # 丟出帶狀態碼的錯誤
    status  # 狀態碼常數
)
from fastapi.middleware.cors import CORSMiddleware  # 處理跨來源請求（瀏覽器的 CORS 規則）
from app.core.config import settings  # 設定：app 名稱、允許的前端網址、資料庫名稱
from app.core.database import SessionLocal, get_db  # SessionLocal：啟動時自己開 session；get_db：路由依賴
from app.core.errors import register_error_handlers  # 統一錯誤格式

from sqlalchemy.exc import SQLAlchemyError  # 所有 SQLAlchemy 錯誤的父類別（/get-db 測試端點用）
from sqlalchemy.orm import Session  # 型別註記
from sqlalchemy import text  # 寫原生 SQL（SELECT NOW()）

# 各功能的路由模組，每個模組裡都有一個 router
from app.routers import audit, auth, conversations, departments, documents, users
from app.services.ingestion import mark_interrupted_as_failed  # 啟動時清理卡在 pending 的文件


# ── 生命週期：yield 之前的程式在伺服器啟動時跑一次，yield 之後的在關閉時跑 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """伺服器啟動時執行一次：上次關機時還在處理的文件標成 failed，管理員才能重新處理。"""
    with SessionLocal() as db:
        mark_interrupted_as_failed(db)
    yield


# ── 建立應用程式 ──
app = FastAPI(title=settings.app_name, lifespan=lifespan)

# ── 中介層：CORS ──
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

# ── 錯誤處理：所有錯誤統一成 {"code","message"} ──
register_error_handlers(app)

# ── 掛上各功能的路由 ──
app.include_router(auth.router)  # /api/v1/auth/...      登入、續期、登出
app.include_router(users.router)  # /api/v1/users、/me    註冊、我的資料、使用者管理
app.include_router(departments.router)  # /api/v1/departments  部門清單
app.include_router(documents.router)  # /api/v1/documents    文件管理（IT 管理員）
app.include_router(conversations.router)  # /api/v1/conversations、/messages  對話與問答
app.include_router(audit.router)  # /api/v1/audit-logs   稽核紀錄（IT 管理員）


# ── 以下是你原本寫的測試端點：確認伺服器與資料庫連線是否正常 ──
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
