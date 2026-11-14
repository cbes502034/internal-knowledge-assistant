"""集中管理設定：全部從環境變數（或專案根目錄的 .env）讀取。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]   # 專案根目錄


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
    login_max_failures: int = 5          # 連續失敗幾次就鎖定
    login_lock_min: int = 15             # 鎖定幾分鐘
    cookie_secure: bool = False          # 正式環境（HTTPS）設為 true

    # 模型
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_timeout_s: float = 120.0
    gen_model: str = "qwen2.5:3b"
    gen_max_tokens: int = 512
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    embed_cache_size: int = 512          # 問題向量的 LRU 快取容量

    # 檢索（預設值都由 data/eval_cases.csv 的評測校準，見 README「評測結果」）
    top_k: int = 5
    candidates: int = 20                 # 向量與關鍵字各取幾筆候選，再用 RRF 融合
    search_mode: str = "vector"          # vector、hybrid、keyword；本資料集純向量最好，代碼多的文件可改 hybrid
    keyword_weight: float = 0.3          # RRF 中關鍵字排名的權重（向量為 1）
    score_threshold: float = 0.56        # 最高向量相似度低於此值、且沒有精確字詞相符 → 拒答

    # 文件
    upload_dir: Path = ROOT_DIR / "data" / "uploads"
    max_upload_mb: int = 10

    # 其他
    cors_origins: str = "http://localhost:5173"
    rate_limit_per_min: int = 20
    trust_proxy_headers: bool = False    # 在 Nginx 後面時設為 true，才採用 X-Real-IP

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
