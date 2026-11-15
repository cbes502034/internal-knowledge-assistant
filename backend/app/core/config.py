from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name : str
    app_env : str
    debug : bool
    secret_key : str

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

    model_config = SettingsConfigDict(env_file = ".env")

settings = Settings()
