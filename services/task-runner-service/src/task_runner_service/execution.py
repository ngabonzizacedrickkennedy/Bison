from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from task_runner_service.backends import Binding, bind, build
from task_runner_service.manifest import load_manifest
from task_runner_service.sandbox import (
    Limits,
    Mount,
    Sandbox,
    SandboxRequest,
    SandboxResult,
    Termination,
    program_kind,
)
from task_runner_service.stream import QueueSink, encode, error_event, output_event, result_event

DEFAULT_WALL_CLOCK_SECONDS = 600

DEFAULT_MEMORY_MB = 512

DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024


def limits_from(declared: dict[str, Any] | None) -> Limits:
    payload = declared if declared else {}

    return Limits(
        wall_clock_seconds=int(payload.get("wall_clock_seconds", DEFAULT_WALL_CLOCK_SECONDS)),
        memory_mb=int(payload.get("memory_mb", DEFAULT_MEMORY_MB)),
        max_output_bytes=int(payload.get("max_output_bytes", DEFAULT_MAX_OUTPUT_BYTES)),
    )


class Runner:
    def __init__(self, runtime_dir: Path | None = None) -> None:
        self._sandboxes = build(runtime_dir)
        self._bindings: dict[str, Binding] = {}

    @property
    def active(self) -> dict[str, Binding]:
        return dict(self._bindings)

    @property
    def available(self) -> list[Sandbox]:
        return list(self._sandboxes.values())

    def plan(self, request: SandboxRequest) -> Binding:
        return bind(load_manifest(), program_kind(request), self._sandboxes)

    async def terminate_all(self, reason: Termination) -> list[str]:
        stopped: list[str] = []

        for sandbox in self._sandboxes.values():
            stopped.extend(await sandbox.terminate_all(reason))

        return stopped

    async def terminate(self, step_id: str, reason: Termination) -> bool:
        binding = self._bindings.get(step_id)

        if binding is None:
            return False

        return await binding.sandbox.terminate(step_id, reason)

    async def stream(self, request: SandboxRequest, binding: Binding) -> AsyncIterator[bytes]:
        sink = QueueSink()
        self._bindings[request.step_id] = binding

        running = asyncio.create_task(self._execute(request, binding, sink))

        try:
            async for chunk in sink.drain():
                yield encode(output_event(chunk))

            outcome = await running
        finally:
            self._bindings.pop(request.step_id, None)

        if isinstance(outcome, SandboxResult):
            yield encode(result_event(outcome))
        else:
            yield encode(error_event(request.step_id, str(outcome)))

    async def _execute(
        self, request: SandboxRequest, binding: Binding, sink: QueueSink
    ) -> SandboxResult | Exception:
        try:
            return await binding.sandbox.run(request, sink)
        except Exception as error:
            return error
        finally:
            await sink.close()


def build_request(step_id: str, payload: dict[str, Any], scope_root: str) -> SandboxRequest:
    mounts = [Mount(path=scope_root, writable=True)]
    mounts.extend(
        Mount(path=str(entry), writable=False) for entry in payload.get("read_only_mounts", [])
    )

    return SandboxRequest(
        step_id=step_id,
        program=str(payload["program"]),
        arguments=[str(entry) for entry in payload.get("arguments", [])],
        working_directory=str(payload.get("working_directory", scope_root)),
        mounts=mounts,
        environment={str(k): str(v) for k, v in payload.get("environment", {}).items()},
        network=bool(payload.get("network", False)),
        limits=limits_from(payload.get("limits")),
    )
