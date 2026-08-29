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
    model_config = SettingsConfigDict(env_prefix="BISON_MEDIATOR_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8700
    project_service_url: str = "http://127.0.0.1:8400"
    model_broker_url: str = "http://127.0.0.1:8300"
    connect_timeout_seconds: float = 5.0
    invoke_timeout_seconds: float = 900.0
    upstream_timeout_seconds: float = 30.0
    engine_prompt_name: str = "engine"
    engine_prompt_version: str = "v1"
    mediator_prompt_name: str = "mediator"
    mediator_prompt_version: str = "v1"
    context_budget_chars: int = 24000
    repair_attempts: int = 2
    data_dir: Path = Field(default_factory=default_data_dir)


@lru_cache(maxsize=1)
def settings() -> Settings:
    resolved = Settings()
    resolved.data_dir.mkdir(parents=True, exist_ok=True)

    return resolved
