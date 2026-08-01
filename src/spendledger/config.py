from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://spendledger:spendledger@localhost:5432/spendledger"
    log_level: str = "INFO"
    auto_create_schema: bool = False
    allowed_origins: list[str] = [
        "http://localhost:3001",
        "http://localhost:4173",
        "http://localhost:5173",
    ]

    outbox_poll_seconds: float = Field(default=1.0, gt=0)
    outbox_batch_size: int = Field(default=50, ge=1, le=500)
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    outbox_lock_timeout_seconds: int = Field(default=60, ge=10, le=3_600)

    api_key_prefix: str = "sl_live_"
    seed_tenant_name: str = "Portfolio Demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
