from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from bison_contracts import SandboxBackend
from wasmtime import (
    Config,
    DirPerms,
    Engine,
    ExitTrap,
    FilePerms,
    Func,
    Linker,
    Module,
    Store,
    Trap,
    WasiConfig,
    WasmtimeError,
)

from task_runner_service.config import settings
from task_runner_service.effects import observe, snapshot
from task_runner_service.relay import OutputRelay
from task_runner_service.sandbox import (
    Enforcement,
    InvalidSandboxRequestError,
    Mount,
    OutputSink,
    OutputStream,
    ProgramKind,
    ProgramKindUnsupportedError,
    SandboxRequest,
    SandboxResult,
    Termination,
    assert_valid,
    program_kind,
    writable_mounts,
)

BACKEND: SandboxBackend = SandboxBackend.wasm

ACCEPTS: frozenset[ProgramKind] = frozenset({"wasm_module"})

ENFORCEMENT = Enforcement(
    filesystem_write_scope=True,
    filesystem_read_scope=True,
    network_isolation=True,
    memory_limit=True,
    process_tree_kill=True,
)

ENTRY_POINT = "_start"

BYTES_PER_MB = 1024 * 1024

POLL_SECONDS = 0.05

READ_CHUNK_BYTES = 64 * 1024


@dataclass
class Execution:
    engine: Engine
    reason: Termination | None


def guest_paths(request: SandboxRequest) -> list[tuple[Mount, str]]:
    primary = writable_mounts(request)[0]
    mapped: list[tuple[Mount, str]] = [(primary, "/")]
    mapped.extend(
        (mount, f"/mnt/{index}")
        for index, mount in enumerate(m for m in request.mounts if m is not primary)
    )

    return mapped


def permissions(mount: Mount) -> tuple[DirPerms, FilePerms]:
    if mount.writable:
        return DirPerms.READ_WRITE, FilePerms.READ_WRITE

    return DirPerms.READ_ONLY, FilePerms.READ_ONLY


def wasi_for(request: SandboxRequest, module: Path, out: Path, err: Path) -> WasiConfig:
    wasi = WasiConfig()
    wasi.argv = [module.name, *request.arguments]
    wasi.env = [[key, value] for key, value in request.environment.items()]
    wasi.stdout_file = str(out)
    wasi.stderr_file = str(err)

    for mount, guest in guest_paths(request):
        directory, files = permissions(mount)
        wasi.preopen_dir(mount.path, guest, directory, files)

    return wasi


def execute(
    engine: Engine, module: Path, wasi: WasiConfig, memory_mb: int
) -> tuple[int | None, str]:
    store = Store(engine)
    store.set_limits(memory_size=memory_mb * BYTES_PER_MB)
    store.set_epoch_deadline(1)
    store.set_wasi(wasi)

    linker = Linker(engine)
    linker.define_wasi()

    try:
        instance = linker.instantiate(store, Module(engine, module.read_bytes()))
        entry = instance.exports(store).get(ENTRY_POINT)

        if not isinstance(entry, Func):
            return None, f"the module exports no {ENTRY_POINT} function"

        entry(store)
    except ExitTrap as exit_trap:
        return exit_trap.code, ""
    except (Trap, WasmtimeError) as error:
        return None, str(error)

    return 0, ""


class WasmSandbox:
    def __init__(self, runtime_dir: Path | None = None) -> None:
        self._runtime_dir = runtime_dir if runtime_dir else settings().data_dir / "runs"
        self._running: dict[str, Execution] = {}

    @property
    def backend(self) -> SandboxBackend:
        return BACKEND

    @property
    def enforcement(self) -> Enforcement:
        return ENFORCEMENT

    @property
    def accepts(self) -> frozenset[ProgramKind]:
        return ACCEPTS

    async def terminate(self, step_id: str, reason: Termination) -> bool:
        execution = self._running.get(step_id)

        if execution is None:
            return False

        if execution.reason is None:
            execution.reason = reason

        execution.engine.increment_epoch()

        return True

    async def terminate_all(self, reason: Termination) -> list[str]:
        running = list(self._running)

        for step_id in running:
            await self.terminate(step_id, reason)

        return running

    async def run(self, request: SandboxRequest, sink: OutputSink) -> SandboxResult:
        assert_valid(request)

        kind = program_kind(request)

        if kind not in ACCEPTS:
            raise ProgramKindUnsupportedError(BACKEND, kind)

        module = Path(request.program)

        if not await asyncio.to_thread(module.is_file):
            raise InvalidSandboxRequestError(f"no module exists at {request.program!r}")

        if request.step_id in self._running:
            raise InvalidSandboxRequestError(f"step {request.step_id} is already running")

        return await self._run(request, sink, module)

    async def _run(self, request: SandboxRequest, sink: OutputSink, module: Path) -> SandboxResult:
        stream_dir = self._runtime_dir / request.step_id
        stream_dir.mkdir(parents=True, exist_ok=True)

        out = stream_dir / "stdout.log"
        err = stream_dir / "stderr.log"
        out.write_bytes(b"")
        err.write_bytes(b"")

        config = Config()
        config.epoch_interruption = True

        execution = Execution(engine=Engine(config), reason=None)
        self._running[request.step_id] = execution

        watched = [mount.path for mount in writable_mounts(request)]
        before = snapshot(watched)
        relay = OutputRelay(request.step_id, sink, request.limits.max_output_bytes)

        started = datetime.now(UTC)
        finished = asyncio.Event()

        tailer = asyncio.create_task(self._tail(request.step_id, relay, out, err, finished))
        watchdog = asyncio.create_task(
            self._watchdog(request.step_id, request.limits.wall_clock_seconds)
        )

        try:
            wasi = wasi_for(request, module, out, err)
            code, detail = await asyncio.to_thread(
                execute, execution.engine, module, wasi, request.limits.memory_mb
            )
        finally:
            finished.set()
            watchdog.cancel()

            with suppress(asyncio.CancelledError):
                await watchdog

            await tailer
            await relay.close()
            del self._running[request.step_id]

        ended = datetime.now(UTC)
        delta = observe(before, watched)
        reason = execution.reason

        return SandboxResult(
            step_id=request.step_id,
            backend=BACKEND,
            exit_code=None if reason else code,
            terminated_by=reason,
            error_message=None if reason or not detail else detail,
            files_written=delta.written,
            files_deleted=delta.deleted,
            files_written_total=delta.written_total,
            files_deleted_total=delta.deleted_total,
            files_truncated=delta.truncated,
            ports_opened=[],
            output_bytes=relay.bytes_written,
            output_truncated=relay.truncated,
            started_at=started,
            ended_at=ended,
        )

    async def _watchdog(self, step_id: str, seconds: int) -> None:
        await asyncio.sleep(seconds)
        await self.terminate(step_id, "wall_clock")

    async def _tail(
        self,
        step_id: str,
        relay: OutputRelay,
        out: Path,
        err: Path,
        finished: asyncio.Event,
    ) -> None:
        handles: dict[OutputStream, BinaryIO] = {
            "stdout": out.open("rb"),
            "stderr": err.open("rb"),
        }

        try:
            while True:
                moved = await self._drain(relay, handles)

                if relay.truncated:
                    await self.terminate(step_id, "output_limit")

                if finished.is_set() and not moved:
                    return

                await asyncio.sleep(POLL_SECONDS)
        finally:
            for handle in handles.values():
                handle.close()

    async def _drain(self, relay: OutputRelay, handles: dict[OutputStream, BinaryIO]) -> bool:
        moved = False

        for stream, handle in handles.items():
            while data := handle.read(READ_CHUNK_BYTES):
                moved = True
                await relay.write(stream, data)

        return moved
