from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from task_runner_service.sandbox import OutputChunk, SandboxResult
from task_runner_service.writes import WriteResult


def output_event(chunk: OutputChunk) -> dict[str, Any]:
    return {
        "event": "output",
        "step_id": chunk.step_id,
        "stream": chunk.stream,
        "sequence": chunk.sequence,
        "text": chunk.text,
    }


def result_event(result: SandboxResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["backend"] = result.backend.value
    payload["started_at"] = result.started_at.isoformat()
    payload["ended_at"] = result.ended_at.isoformat()

    return {"event": "result", **payload}


def write_event(result: WriteResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["started_at"] = result.started_at.isoformat()
    payload["ended_at"] = result.ended_at.isoformat()

    return {"event": "write", **payload}


def error_event(step_id: str, detail: str) -> dict[str, Any]:
    return {"event": "error", "step_id": step_id, "detail": detail}


def encode(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")


class QueueSink:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[OutputChunk | None] = asyncio.Queue()

    async def emit(self, chunk: OutputChunk) -> None:
        await self._queue.put(chunk)

    async def close(self) -> None:
        await self._queue.put(None)

    async def drain(self) -> AsyncIterator[OutputChunk]:
        while (chunk := await self._queue.get()) is not None:
            yield chunk
