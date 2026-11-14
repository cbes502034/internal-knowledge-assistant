"""應用程式進入點：uvicorn app.main:app --reload"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.llm_service import LLMUnavailableError, get_llm
from app.db import SessionLocal, get_db
from app.errors import AppError, register_error_handlers
from app.models import Document
from app.routers import audit, auth, conversations, departments, documents, eval, users

API_PREFIX = "/api/v1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")


PLACEHOLDER_SECRETS = {"change-me", "change-me-generate-a-long-random-string"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """文件處理是這個行程的背景工作；行程重啟後「處理中」的文件不會有人接手，
    若不處理會永遠卡住（也無法重新處理）。啟動時標成失敗，IT 可以按「重新處理」。
    假設只有一個 API 行程（docker-compose 的設定）；多個行程時要改用工作佇列。"""
    try:
        with SessionLocal() as db:
            stuck = db.execute(update(Document).where(Document.status == "pending").values(status="failed"))
            db.commit()
            if stuck.rowcount:
                logger.warning("marked %d interrupted document(s) as failed", stuck.rowcount)
    except Exception:
        logger.warning("startup recovery skipped: database not reachable")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.jwt_secret in PLACEHOLDER_SECRETS:
        raise RuntimeError("JWT_SECRET 還是範本裡的預設值：任何人都能用它偽造登入權杖。請在 .env 換成 32 字元以上的隨機字串。")
    if len(settings.jwt_secret) < 32:
        logger.warning("JWT_SECRET 太短（%d 字元），正式環境請改用 32 字元以上的隨機字串", len(settings.jwt_secret))

    app = FastAPI(title="內部知識助理 API", version="1.0.0",
                  lifespan=lifespan, docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,           # refresh token 放在 cookie
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)

    for module in (auth, users, departments, conversations, documents, eval, audit):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get(f"{API_PREFIX}/health", tags=["health"])
    def health():
        return {"status": "ok"}

    @app.get(f"{API_PREFIX}/health/db", tags=["health"])
    def health_db(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get(f"{API_PREFIX}/health/llm", tags=["health"])
    def health_llm():
        """檢查 Ollama 是否連得上、需要的兩個模型是否已下載。"""
        llm = get_llm()
        try:
            installed = llm.ping()
        except LLMUnavailableError:
            raise AppError(503, "llm_unavailable", "無法連線到 Ollama") from None
        names = {name.split(":latest")[0] for name in installed} | set(installed)
        missing = [m for m in (llm.embed_model, llm.gen_model) if m not in names]
        return {"status": "ok" if not missing else "degraded", "missing_models": missing}

    return app


app = create_app()
