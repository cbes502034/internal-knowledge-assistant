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

    model_config = SettingsConfigDict(env_file = ".env")

settings = Settings()
