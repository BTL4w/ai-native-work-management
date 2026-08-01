"""Typed environment configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_POSTGRESQL_ASYNC_URL_PREFIX = "postgresql+psycopg://"


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        extra="ignore",
    )

    name: str = "Work Management API"
    version: str = "0.1.0"
    environment: Literal["local", "test", "production"] = "local"
    debug: bool = False
    database_url: str = (
        "postgresql+psycopg://work_management:work_management@localhost:5432/work_management"
    )

    @field_validator("database_url")
    @classmethod
    def require_async_postgresql_driver(cls, value: str) -> str:
        """Reject database URLs that bypass the selected PostgreSQL async driver."""

        if not value.startswith(_POSTGRESQL_ASYNC_URL_PREFIX):
            msg = f"database_url must start with {_POSTGRESQL_ASYNC_URL_PREFIX}"
            raise ValueError(msg)
        return value


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings object per process."""

    return Settings()
