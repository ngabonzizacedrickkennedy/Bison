from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum
from time import monotonic

from model_broker_service.backends.base import (
    BackendModel,
    BackendUnavailableError,
    ModelBackend,
)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class BackendCircuitOpenError(BackendUnavailableError):
    def __init__(self, backend: str) -> None:
        super().__init__(backend, "circuit open after repeated failures")


class CircuitBreaker:
    def __init__(self, fail_max: int, reset_seconds: float) -> None:
        self._fail_max = fail_max
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False
        self._state = CircuitState.CLOSED
        self._lock = asyncio.Lock()

    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and monotonic() - self._opened_at >= self._reset_seconds
        ):
            self._state = CircuitState.HALF_OPEN

        return self._state

    async def run[T](self, backend: str, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            state = self.state()

            if state is CircuitState.OPEN:
                raise BackendCircuitOpenError(backend)

            if state is CircuitState.HALF_OPEN:
                if self._trial_in_flight:
                    raise BackendCircuitOpenError(backend)

                self._trial_in_flight = True

        try:
            result = await operation()
        except Exception:
            async with self._lock:
                self._failures += 1
                self._trial_in_flight = False

                if self._state is CircuitState.HALF_OPEN or self._failures >= self._fail_max:
                    self._state = CircuitState.OPEN
                    self._opened_at = monotonic()

            raise

        async with self._lock:
            self._failures = 0
            self._trial_in_flight = False
            self._state = CircuitState.CLOSED

        return result


class CircuitBrokenBackend(ModelBackend):
    def __init__(self, inner: ModelBackend, fail_max: int, reset_seconds: float) -> None:
        self.name = inner.name
        self.locality = inner.locality
        self._inner = inner
        self._breaker = CircuitBreaker(fail_max, reset_seconds)

    async def healthy(self) -> bool:
        if self._breaker.state() is CircuitState.OPEN:
            return False

        return await self._inner.healthy()

    async def state(self) -> str:
        circuit = self._breaker.state()

        if circuit is not CircuitState.CLOSED:
            return str(circuit.value)

        return "ok" if await self._inner.healthy() else "unreachable"

    async def list_models(self) -> list[BackendModel]:
        return await self._breaker.run(self.name, self._inner.list_models)

    async def generate(
        self,
        model_id: str,
        prompt: str,
        *,
        structured: bool,
        timeout_seconds: float,
    ) -> str:
        return await self._breaker.run(
            self.name,
            lambda: self._inner.generate(
                model_id,
                prompt,
                structured=structured,
                timeout_seconds=timeout_seconds,
            ),
        )

    async def close(self) -> None:
        await self._inner.close()
