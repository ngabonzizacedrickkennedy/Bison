from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_workspace_root() -> Path:
    override = os.environ.get("BISON_DATA_DIR")

    if override:
        return Path(override) / "projects"

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"

    return base / "BISON" / "projects"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BISON_ROUTER_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8600
    project_service_url: str = "http://127.0.0.1:8400"
    model_broker_url: str = "http://127.0.0.1:8300"
    connect_timeout_seconds: float = 5.0
    invoke_timeout_seconds: float = 600.0
    upstream_timeout_seconds: float = 30.0
    prompt_name: str = "router"
    prompt_version: str = "v4"
    context_budget_chars: int = 24000
    repair_attempts: int = 1
    workspace_root: Path = Field(default_factory=default_workspace_root)


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
