from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic


@dataclass(slots=True)
class Entry[T]:
    value: T
    expires_at: float


class TtlCache[T]:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, Entry[T]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def peek(self, key: str) -> T | None:
        entry = self._entries.get(key)

        if entry is None or entry.expires_at <= monotonic():
            return None

        return entry.value

    async def get_or_load(self, key: str, loader: Callable[[], Awaitable[T]]) -> T:
        cached = self.peek(key)

        if cached is not None:
            return cached

        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self.peek(key)

            if cached is not None:
                return cached

            value = await loader()
            self._entries[key] = Entry(value=value, expires_at=monotonic() + self._ttl)
            return value

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
