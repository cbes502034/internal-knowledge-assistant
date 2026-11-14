"""集中管理設定：全部從環境變數（或專案根目錄的 .env）讀取。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]   # 專案根目錄（LLM/）


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    # 資料庫
    database_url: str = "postgresql+psycopg://assistant:change-me-local-only@127.0.0.1:5432/assistant"

    # 驗證
    jwt_secret: str = "change-me"
    jwt_alg: str = "HS256"
    access_ttl_min: int = 15
    refresh_ttl_hours: int = 8
    idle_timeout_min: int = 15

    # 模型
    ollama_url: str = "http://127.0.0.1:11434"
    gen_model: str = "qwen2.5:3b"
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024

    # 檢索
    top_k: int = 5
    score_threshold: float = 0.45

    # 其他
    cors_origins: str = "http://localhost:5173"
    rate_limit_per_min: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
