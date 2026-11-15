"""
【檔案用途】集中管理所有設定。值的來源優先順序：環境變數 > backend/.env 檔 > 這裡寫的預設值。
欄位名稱不分大小寫對應：例如 .env 裡的 POSTGRES_PORT 會填進 postgres_port。
沒有預設值的欄位（app_name、secret_key…）在 .env 裡缺少時，程式一啟動就會報錯，不會帶著錯誤設定跑下去。

被誰使用：幾乎所有檔案都 from app.core.config import settings。
"""

# BaseSettings：會自動從環境變數與 .env 讀值並轉型的設定類別；SettingsConfigDict：設定它去讀哪個檔
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """所有設定欄位；型別註記決定讀進來要轉成什麼型別（例如 "5434" → 5434）。"""

    # ── 應用程式基本設定（必填）──
    app_name : str
    app_env : str  # production 時 refresh cookie 會加上 Secure（只走 HTTPS）
    debug : bool
    secret_key : str  # 簽 JWT 用的密鑰，建議至少 32 個字元的亂數

    # ── 資料庫連線（必填）──
    postgres_database : str
    postgres_user : str
    postgres_password : str
    postgres_host : str
    postgres_port : int

    # 模型服務（Ollama）；都有預設值，.env 不寫也能跑
    ollama_base_url : str = "http://127.0.0.1:11434"
    embed_model : str = "bge-m3"
    chat_model : str = "qwen2.5:3b"
    llm_timeout : float = 120.0  # 本機 CPU 跑 3B 模型生成較慢，逾時要抓寬

    # 前端網址（逗號分隔）；瀏覽器只允許這些來源帶 cookie 呼叫 API
    cors_origins : str = "http://127.0.0.1:5500,http://localhost:5500"

    # 上傳的原始檔放哪裡（相對於啟動 uvicorn 的目錄）；重新處理文件時會從這裡讀
    upload_dir : str = "uploads"

    # refresh token 有效時數（一個工作天）與伺服器端閒置登出的分鐘數
    refresh_token_hours : int = 8
    idle_timeout_minutes : int = 30

    # 告訴 BaseSettings 去讀 .env（相對於啟動程式的目錄，所以要在 backend 底下啟動）
    model_config = SettingsConfigDict(env_file = ".env")

# 建立一份全域共用的設定物件：import 時就讀好，之後各處直接用 settings.xxx
settings = Settings()
