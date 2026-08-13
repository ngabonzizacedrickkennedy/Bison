from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def data_dir() -> Path:
    override = os.environ.get("BISON_DATA_DIR")
    if override:
        path = Path(override)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
        path = base / "BISON"

    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "bison.db"


def database_url() -> str:
    return f"sqlite+aiosqlite:///{database_path()}"


SUPPORTED_DATABASE_BACKENDS = frozenset({"sqlite"})


class UnsupportedBackendError(RuntimeError):
    pass


def bind_database(backend: str | None) -> str:
    if backend not in SUPPORTED_DATABASE_BACKENDS:
        raise UnsupportedBackendError(
            f"capability manifest selected database backend {backend!r}, "
            f"but this service implements {sorted(SUPPORTED_DATABASE_BACKENDS)}"
        )

    return database_url()


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(database_url(), echo=False, future=True)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(engine(), expire_on_commit=False)
    return _session_factory


def configure_engine(url: str) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(url, echo=False, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
