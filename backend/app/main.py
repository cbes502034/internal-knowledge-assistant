"""應用程式進入點：uvicorn app.main:app --reload"""
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.llm_service import LLMUnavailableError, get_llm
from app.db import get_db
from app.errors import AppError, register_error_handlers
from app.routers import audit, auth, conversations, departments, documents, eval, users

API_PREFIX = "/api/v1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")


def create_app() -> FastAPI:
    settings = get_settings()
    if len(settings.jwt_secret) < 32:
        logger.warning("JWT_SECRET 太短（%d 字元），正式環境請改用 32 字元以上的隨機字串", len(settings.jwt_secret))

    app = FastAPI(title="內部知識助理 API", version="1.0.0",
                  docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")

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
