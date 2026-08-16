from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BISON_ANALYST_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8500
    project_service_url: str = "http://127.0.0.1:8400"
    model_broker_url: str = "http://127.0.0.1:8300"
    connect_timeout_seconds: float = 5.0
    invoke_timeout_seconds: float = 300.0
    upstream_timeout_seconds: float = 30.0
    prompt_version: str = "v3"
    confidence_threshold: float = 0.75
    context_budget_chars: int = 24000
    repair_attempts: int = 1


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
