from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

Locality = Literal["local", "remote"]


@dataclass(frozen=True, slots=True)
class BackendModel:
    model_id: str
    provider: str
    locality: Locality
    size_gb: float | None
    context_window: int | None


class BackendError(RuntimeError):
    def __init__(self, backend: str, message: str) -> None:
        super().__init__(f"{backend}: {message}")
        self.backend = backend


class BackendUnavailableError(BackendError):
    pass


class BackendTimeoutError(BackendError):
    pass


@dataclass(frozen=True, slots=True)
class PullProgress:
    status: str
    completed_bytes: int | None
    total_bytes: int | None


class ModelBackend(ABC):
    name: str
    locality: Locality

    @abstractmethod
    async def healthy(self) -> bool: ...

    @abstractmethod
    async def list_models(self) -> list[BackendModel]: ...

    @abstractmethod
    async def generate(
        self,
        model_id: str,
        prompt: str,
        *,
        structured: bool,
        timeout_seconds: float,
    ) -> str: ...

    @abstractmethod
    def pull(self, model_id: str) -> AsyncIterator[PullProgress]: ...

    @abstractmethod
    async def close(self) -> None: ...

    async def state(self) -> str:
        return "ok" if await self.healthy() else "unreachable"
