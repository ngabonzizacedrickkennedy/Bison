from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import win32api
import win32con
import win32job
from bison_contracts import SandboxBackend

from task_runner_service.config import settings
from task_runner_service.effects import observe, snapshot
from task_runner_service.relay import OutputRelay
from task_runner_service.sandbox import (
    Enforcement,
    InvalidSandboxRequestError,
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

BACKEND: SandboxBackend = SandboxBackend.job_object

ACCEPTS: frozenset[ProgramKind] = frozenset({"native"})

ENFORCEMENT = Enforcement(
    filesystem_scope=False,
    network_isolation=False,
    memory_limit=True,
    process_tree_kill=True,
)

BYTES_PER_MB = 1024 * 1024

MAX_ACTIVE_PROCESSES = 32

READ_CHUNK_BYTES = 64 * 1024

TERMINATION_EXIT_CODE = 1

LIMIT_FLAGS: int = (
    win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
    | win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
    | win32job.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
)

PROCESS_ACCESS: int = win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE


@dataclass
class Execution:
    job: int
    reason: Termination | None


def create_job(memory_mb: int) -> int:
    job: int = win32job.CreateJobObject(None, "")
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)

    limits["BasicLimitInformation"]["LimitFlags"] = LIMIT_FLAGS
    limits["BasicLimitInformation"]["ActiveProcessLimit"] = MAX_ACTIVE_PROCESSES
    limits["ProcessMemoryLimit"] = memory_mb * BYTES_PER_MB
    limits["JobMemoryLimit"] = memory_mb * BYTES_PER_MB

    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)

    return job


def enrol(job: int, pid: int) -> None:
    handle: int = win32api.OpenProcess(PROCESS_ACCESS, False, pid)

    try:
        win32job.AssignProcessToJobObject(job, handle)
    finally:
        win32api.CloseHandle(handle)


class JobObjectSandbox:
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

        with suppress(BaseException):
            win32job.TerminateJobObject(execution.job, TERMINATION_EXIT_CODE)

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

        if request.step_id in self._running:
            raise InvalidSandboxRequestError(f"step {request.step_id} is already running")

        return await self._run(request, sink)

    async def _run(self, request: SandboxRequest, sink: OutputSink) -> SandboxResult:
        watched = [mount.path for mount in writable_mounts(request)]
        before = snapshot(watched)
        relay = OutputRelay(request.step_id, sink, request.limits.max_output_bytes)

        started = datetime.now(UTC)
        execution = Execution(job=create_job(request.limits.memory_mb), reason=None)

        try:
            process = await asyncio.create_subprocess_exec(
                request.program,
                *request.arguments,
                cwd=request.working_directory,
                env=dict(request.environment),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            win32api.CloseHandle(execution.job)

            raise InvalidSandboxRequestError(
                f"{request.program!r} could not be started: {error.strerror or error}"
            ) from error

        self._running[request.step_id] = execution

        try:
            enrol(execution.job, process.pid)

            watchdog = asyncio.create_task(
                self._watchdog(request.step_id, request.limits.wall_clock_seconds)
            )

            await asyncio.gather(
                self._pump(relay, "stdout", process.stdout),
                self._pump(relay, "stderr", process.stderr),
            )

            code = await process.wait()

            watchdog.cancel()

            with suppress(asyncio.CancelledError):
                await watchdog

            await relay.close()
        finally:
            del self._running[request.step_id]
            win32api.CloseHandle(execution.job)

        ended = datetime.now(UTC)
        delta = observe(before, watched)
        reason = execution.reason

        return SandboxResult(
            step_id=request.step_id,
            backend=BACKEND,
            exit_code=None if reason else code,
            terminated_by=reason,
            error_message=None,
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

    async def _pump(
        self, relay: OutputRelay, stream: OutputStream, reader: asyncio.StreamReader | None
    ) -> None:
        if reader is None:
            return

        while data := await reader.read(READ_CHUNK_BYTES):
            await relay.write(stream, data)

            if relay.truncated:
                await self.terminate(relay.step_id, "output_limit")
