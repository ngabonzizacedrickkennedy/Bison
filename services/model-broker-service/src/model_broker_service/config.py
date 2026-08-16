from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    override = os.environ.get("BISON_DATA_DIR")
    if override:
        return Path(override)

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "BISON"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BISON_BROKER_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8300
    data_dir: Path = Field(default_factory=default_data_dir)
    ollama_base_url: str = "http://localhost:11434"
    connect_timeout_seconds: float = 5.0
    invoke_timeout_seconds: float = 120.0
    local_concurrency: int = 1
    models_ttl_seconds: float = 30.0
    breaker_fail_max: int = 3
    breaker_reset_seconds: float = 30.0
    openrouter_base_url: str = "https://openrouter.ai"
    openrouter_api_key: str = ""
    openrouter_free_only: bool = True
    catalog_fetch_timeout_seconds: float = 60.0
    catalog_refresh_seconds: float = 21600.0


@lru_cache(maxsize=1)
def settings() -> Settings:
    resolved = Settings()
    resolved.data_dir.mkdir(parents=True, exist_ok=True)
    return resolved
