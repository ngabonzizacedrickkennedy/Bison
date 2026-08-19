from __future__ import annotations

import asyncio
from contextlib import suppress

import psutil

SAMPLE_INTERVAL_SECONDS = 0.2

MAX_TRACKED_PIDS = 256


def tree(root: int, known: set[int]) -> set[int]:
    if root <= 0:
        return set(known)

    found = set(known)
    found.add(root)

    with suppress(psutil.Error):
        found.update(child.pid for child in psutil.Process(root).children(recursive=True))

    return set(sorted(found)[:MAX_TRACKED_PIDS])


def listening(pids: set[int]) -> set[int]:
    if not pids:
        return set()

    try:
        table = psutil.net_connections(kind="inet")
    except (psutil.Error, OSError):
        return set()

    return {
        entry.laddr.port
        for entry in table
        if entry.pid in pids and entry.status == psutil.CONN_LISTEN and entry.laddr
    }


class PortWatcher:
    def __init__(self, root: int, interval: float = SAMPLE_INTERVAL_SECONDS) -> None:
        self._root = root
        self._interval = interval
        self._pids: set[int] = set()
        self._seen: set[int] = set()
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def observed(self) -> list[int]:
        return sorted(self._seen)

    @property
    def tracked(self) -> list[int]:
        return sorted(self._pids)

    def sample(self) -> None:
        self._pids = tree(self._root, self._pids)
        self._seen.update(listening(self._pids))

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        if self._task is None:
            return

        self._stopping.set()

        await self._task

        self._task = None

        await asyncio.to_thread(self.sample)

    async def _poll(self) -> None:
        while not self._stopping.is_set():
            await asyncio.to_thread(self.sample)

            with suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), self._interval)
