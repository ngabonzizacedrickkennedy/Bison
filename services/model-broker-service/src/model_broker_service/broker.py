from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import Enum
from time import perf_counter

from bison_contracts import InvokeRequest, InvokeResponse

from model_broker_service.backends import (
    BackendError,
    BackendModel,
    ModelBackend,
    PullProgress,
)
from model_broker_service.cache import TtlCache


def enum_value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)

    return str(value)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ModelNotFoundError(RuntimeError):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"no reachable backend serves model {model_id}")
        self.model_id = model_id


class ModelBroker:
    def __init__(
        self,
        backends: list[ModelBackend],
        local_concurrency: int,
        models_ttl_seconds: float,
    ) -> None:
        self._backends = backends
        self._local_gate = asyncio.Semaphore(local_concurrency)
        self._models: TtlCache[list[BackendModel]] = TtlCache(models_ttl_seconds)

    async def health(self) -> dict[str, str]:
        states = await asyncio.gather(*(backend.state() for backend in self._backends))
        return dict(zip((backend.name for backend in self._backends), states, strict=True))

    async def list_models(self) -> list[BackendModel]:
        collected: list[BackendModel] = []

        for backend in self._backends:
            try:
                collected.extend(await self._models_for(backend))
            except BackendError:
                continue

        return collected

    async def candidates(self, model_id: str) -> list[ModelBackend]:
        serving: list[ModelBackend] = []
        failure: BackendError | None = None

        for backend in self._backends:
            try:
                models = await self._models_for(backend)
            except BackendError as error:
                failure = error
                continue

            if any(model.model_id == model_id for model in models):
                serving.append(backend)

        if serving:
            return serving

        if failure is not None:
            raise failure

        raise ModelNotFoundError(model_id)

    async def invoke(self, request: InvokeRequest) -> InvokeResponse:
        serving = await self.candidates(request.model_id)
        structured = enum_value(request.mode) == "structured"
        timeout_seconds = request.timeout_ms / 1000
        failed_over_from: str | None = None
        last_error: BackendError | None = None

        for backend in serving:
            started = perf_counter()

            try:
                text = await self._generate(
                    backend,
                    request.model_id,
                    request.prompt,
                    structured=structured,
                    timeout_seconds=timeout_seconds,
                )
            except BackendError as error:
                last_error = error
                failed_over_from = backend.name
                self._models.invalidate(backend.name)
                continue

            return InvokeResponse(
                request_id=request.request_id,
                model_id=request.model_id,
                engine_id=request.engine_id,
                response=text,
                failed_over_from=failed_over_from,
                latency_ms=int((perf_counter() - started) * 1000),
                completed_at=utc_now(),
            )

        raise last_error if last_error is not None else ModelNotFoundError(request.model_id)

    async def pull(self, model_id: str) -> AsyncIterator[PullProgress]:
        for backend in self._backends:
            if backend.locality != "local":
                continue

            async for progress in backend.pull(model_id):
                yield progress

            self._models.invalidate(backend.name)
            return

        raise ModelNotFoundError(model_id)

    async def close(self) -> None:
        for backend in self._backends:
            await backend.close()

    async def _generate(
        self,
        backend: ModelBackend,
        model_id: str,
        prompt: str,
        *,
        structured: bool,
        timeout_seconds: float,
    ) -> str:
        if backend.locality != "local":
            return await backend.generate(
                model_id, prompt, structured=structured, timeout_seconds=timeout_seconds
            )

        async with self._local_gate:
            return await backend.generate(
                model_id, prompt, structured=structured, timeout_seconds=timeout_seconds
            )

    async def _models_for(self, backend: ModelBackend) -> list[BackendModel]:
        return await self._models.get_or_load(backend.name, backend.list_models)
