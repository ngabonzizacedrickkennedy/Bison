from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from model_broker_service.config import settings


class UnsupportedDatabaseBackendError(RuntimeError):
    def __init__(self, backend: str | None) -> None:
        super().__init__(
            f"model-broker-service does not implement database backend {backend or 'none'}"
        )
        self.backend = backend


def database_path() -> Path:
    return settings().data_dir / "broker.db"


def bind_database(backend: str | None) -> str:
    if backend != "sqlite":
        raise UnsupportedDatabaseBackendError(backend)

    return f"sqlite+aiosqlite:///{database_path()}"


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_engine(url: str) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(url, echo=False, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("database engine was not configured at startup")

    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def dispose() -> None:
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _session_factory = None
