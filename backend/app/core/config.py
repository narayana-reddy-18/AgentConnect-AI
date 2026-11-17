from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    app_name: str = "AgentConnect AI API"
    database_url: SecretStr
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    semantic_match_threshold: float = Field(default=0.3, ge=-1, le=1)
    semantic_match_limit: int = Field(default=3, ge=1, le=20)
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/callback"
    frontend_base_url: str = "http://localhost:5173"
    oauth_transaction_encryption_key: SecretStr | None = None
    oauth_transaction_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    session_cookie_name: str = "agentconnect_session"
    oauth_transaction_cookie_name: str = "agentconnect_oauth"
    session_cookie_secure: bool = True
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_ttl_seconds: int = Field(default=28800, ge=300, le=2592000)
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    csrf_trusted_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def require_mysql_pymysql(cls, value: SecretStr) -> SecretStr:
        try:
            drivername = make_url(value.get_secret_value()).drivername
        except ArgumentError as exc:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from exc

        if drivername != "mysql+pymysql":
            raise ValueError("DATABASE_URL must use the mysql+pymysql driver")
        return value


@lru_cache
def get_settings() -> Settings:
    if os.getenv("APP_ENV", "").lower() == "test":
        return Settings(_env_file=None)
    return Settings()


settings = get_settings()
