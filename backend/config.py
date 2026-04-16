from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    mistral_api_key: str
    database_url: str = "postgresql://aob_user:aob_password@localhost:5432/aob_db"

    slack_webhook_url: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    support_email: str = ""

    secret_key: str = "change-me-in-production"
    log_level: str = "INFO"

    # mistral-small-latest supports tool calling and is available on the free tier
    mistral_model: str = "mistral-small-latest"
    mistral_temperature: float = 0.0

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
