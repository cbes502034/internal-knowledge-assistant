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

    model_config = SettingsConfigDict(env_file = ".env")

settings = Settings()
