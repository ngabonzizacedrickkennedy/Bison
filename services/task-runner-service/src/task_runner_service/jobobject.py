from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pywintypes
import win32api
import win32con
import win32job
from bison_contracts import SandboxBackend

from task_runner_service import integrity, ports, process
from task_runner_service.config import settings
from task_runner_service.effects import observe, snapshot
from task_runner_service.process import Launch
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
    filesystem_write_scope=True,
    filesystem_read_scope=False,
    network_isolation=False,
    memory_limit=True,
    process_tree_kill=True,
)

BYTES_PER_MB = 1024 * 1024

MAX_ACTIVE_PROCESSES = 32

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


@dataclass
class Labels:
    previous: dict[Path, str | None] = field(default_factory=dict)

    def apply(self, directories: list[Path]) -> None:
        for directory in directories:
            self.previous[directory] = integrity.label_of(directory)
            integrity.label_low(directory)

    def restore(self) -> None:
        for directory, sid in self.previous.items():
            with suppress(BaseException):
                integrity.apply_label(directory, sid)

        self.previous.clear()


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
        labels = Labels()
        token = integrity.restricted_token()

        try:
            labels.apply([Path(path) for path in watched])
            launch = self._start(request, token)
        except BaseException:
            labels.restore()
            integrity.close(token)
            win32api.CloseHandle(execution.job)

            raise

        self._running[request.step_id] = execution

        watcher = ports.PortWatcher(launch.pid)

        try:
            enrol(execution.job, launch.pid)
            process.resume(launch)
            watcher.start()

            watchdog = asyncio.create_task(
                self._watchdog(request.step_id, request.limits.wall_clock_seconds)
            )

            await asyncio.gather(
                self._pump(relay, "stdout", launch.stdout),
                self._pump(relay, "stderr", launch.stderr),
            )

            code = await process.wait(launch)

            watchdog.cancel()

            with suppress(asyncio.CancelledError):
                await watchdog

            await relay.close()
        finally:
            await watcher.stop()

            del self._running[request.step_id]
            process.close(launch)
            labels.restore()
            integrity.close(token)
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
            ports_opened=watcher.observed,
            output_bytes=relay.bytes_written,
            output_truncated=relay.truncated,
            started_at=started,
            ended_at=ended,
        )

    def _start(self, request: SandboxRequest, token: int) -> Launch:
        try:
            return process.start(
                request.program,
                request.arguments,
                Path(request.working_directory),
                request.environment,
                token,
            )
        except pywintypes.error as error:
            raise InvalidSandboxRequestError(
                f"{request.program!r} could not be started: {error.strerror or error}"
            ) from error

    async def _watchdog(self, step_id: str, seconds: int) -> None:
        await asyncio.sleep(seconds)
        await self.terminate(step_id, "wall_clock")

    async def _pump(self, relay: OutputRelay, stream: OutputStream, handle: int) -> None:
        while data := await process.read(handle):
            await relay.write(stream, data)

            if relay.truncated:
                await self.terminate(relay.step_id, "output_limit")
