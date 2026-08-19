from __future__ import annotations

import asyncio
import shutil
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final

from bison_contracts import SandboxBackend

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
    SandboxUnavailableError,
    Termination,
    assert_valid,
    program_kind,
    writable_mounts,
)
from task_runner_service.venvs import slug

BACKEND: SandboxBackend = SandboxBackend.docker

ACCEPTS: frozenset[ProgramKind] = frozenset({"native"})

ENFORCEMENT = Enforcement(
    filesystem_write_scope=True,
    filesystem_read_scope=True,
    network_isolation=True,
    memory_limit=True,
    process_tree_kill=True,
)

DEFAULT_IMAGE: Final[str] = "python:3.12-slim"

EXECUTABLE: Final[str] = "docker"

CONTAINER_PREFIX: Final[str] = "bison"

PRIMARY_GUEST_PATH: Final[str] = "/workspace"

TEMPORARY_GUEST_PATH: Final[str] = "/tmp"  # noqa: S108

MAX_ACTIVE_PROCESSES: Final[int] = 32

READ_CHUNK_BYTES: Final[int] = 64 * 1024

CREATE_TIMEOUT_SECONDS: Final[int] = 30

TEARDOWN_TIMEOUT_SECONDS: Final[int] = 30


@dataclass
class Execution:
    container: str
    reason: Termination | None


def available() -> bool:
    return shutil.which(EXECUTABLE) is not None


def executable() -> str:
    found = shutil.which(EXECUTABLE)

    if found is None:
        raise SandboxUnavailableError(BACKEND.value, "docker is not on PATH")

    return found


def container_name(step_id: str) -> str:
    return f"{CONTAINER_PREFIX}-{slug(step_id)}"


def guest_paths(request: SandboxRequest) -> list[tuple[Mount, str]]:
    primary = writable_mounts(request)[0]
    mapped: list[tuple[Mount, str]] = [(primary, PRIMARY_GUEST_PATH)]
    mapped.extend(
        (mount, f"/mnt/{index}")
        for index, mount in enumerate(m for m in request.mounts if m is not primary)
    )

    return mapped


def translate(path: str, mapped: list[tuple[Mount, str]]) -> str | None:
    candidate = PureWindowsPath(path)

    if ".." in candidate.parts:
        return None

    for mount, guest in mapped:
        host = PureWindowsPath(mount.path)
        absolute = candidate if candidate.is_absolute() else host / candidate

        try:
            relative = absolute.relative_to(host)
        except ValueError:
            continue

        return str(PurePosixPath(guest, *relative.parts))

    return None


def mount_argument(mount: Mount, guest: str) -> str:
    if "," in mount.path:
        raise InvalidSandboxRequestError(
            f"mount {mount.path!r} contains a comma, which docker cannot bind"
        )

    declared = ["type=bind", f"source={mount.path}", f"target={guest}"]

    if not mount.writable:
        declared.append("readonly")

    return ",".join(declared)


def create_command(
    request: SandboxRequest, container: str, image: str, mapped: list[tuple[Mount, str]]
) -> list[str]:
    working_directory = translate(request.working_directory, mapped)

    if working_directory is None:
        raise InvalidSandboxRequestError(
            f"the working directory {request.working_directory!r} maps to no mounted path"
        )

    command = [
        "create",
        "--name",
        container,
        "--pull",
        "never",
        "--network",
        "none",
        "--memory",
        f"{request.limits.memory_mb}m",
        "--memory-swap",
        f"{request.limits.memory_mb}m",
        "--pids-limit",
        str(MAX_ACTIVE_PROCESSES),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        TEMPORARY_GUEST_PATH,
        "--workdir",
        working_directory,
    ]

    for mount, guest in mapped:
        command.extend(["--mount", mount_argument(mount, guest)])

    for key, value in request.environment.items():
        command.extend(["--env", f"{key}={value}"])

    command.extend(["--entrypoint", request.program, image, *request.arguments])

    return command


class DockerSandbox:
    def __init__(self, runtime_dir: Path | None = None, image: str = DEFAULT_IMAGE) -> None:
        self._runtime_dir = runtime_dir if runtime_dir else settings().data_dir / "runs"
        self._image = image
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

    @property
    def image(self) -> str:
        return self._image

    async def terminate(self, step_id: str, reason: Termination) -> bool:
        execution = self._running.get(step_id)

        if execution is None:
            return False

        if execution.reason is None:
            execution.reason = reason

        await self._silently(["kill", "--signal", "KILL", execution.container])

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
        mapped = guest_paths(request)
        watched = [mount.path for mount in writable_mounts(request)]
        before = snapshot(watched)
        relay = OutputRelay(request.step_id, sink, request.limits.max_output_bytes)

        container = container_name(request.step_id)
        command = create_command(request, container, self._image, mapped)

        started = datetime.now(UTC)

        await self._silently(["rm", "--force", "--volumes", container])
        await self._create(command, container)

        self._running[request.step_id] = Execution(container=container, reason=None)

        watchdog = asyncio.create_task(
            self._watchdog(request.step_id, request.limits.wall_clock_seconds)
        )

        try:
            code = await self._attach(relay, container)
        finally:
            watchdog.cancel()

            with suppress(asyncio.CancelledError):
                await watchdog

            await relay.close()

            execution = self._running.pop(request.step_id)

            await self._silently(["rm", "--force", "--volumes", container])

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

    async def _create(self, command: list[str], container: str) -> None:
        process = await asyncio.create_subprocess_exec(
            executable(),
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _out, err = await asyncio.wait_for(process.communicate(), CREATE_TIMEOUT_SECONDS)
        except TimeoutError as expired:
            process.kill()

            await self._silently(["rm", "--force", "--volumes", container])

            raise SandboxUnavailableError(
                BACKEND.value, f"docker create did not answer within {CREATE_TIMEOUT_SECONDS}s"
            ) from expired

        if process.returncode != 0:
            detail = err.decode("utf-8", "replace").strip()

            raise InvalidSandboxRequestError(detail or f"docker create exited {process.returncode}")

    async def _attach(self, relay: OutputRelay, container: str) -> int | None:
        process = await asyncio.create_subprocess_exec(
            executable(),
            "start",
            "--attach",
            container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await asyncio.gather(
            self._pump(relay, "stdout", process.stdout),
            self._pump(relay, "stderr", process.stderr),
        )

        return await process.wait()

    async def _pump(
        self, relay: OutputRelay, stream: OutputStream, reader: asyncio.StreamReader | None
    ) -> None:
        if reader is None:
            return

        while data := await reader.read(READ_CHUNK_BYTES):
            await relay.write(stream, data)

            if relay.truncated:
                await self.terminate(relay.step_id, "output_limit")

    async def _watchdog(self, step_id: str, seconds: int) -> None:
        await asyncio.sleep(seconds)
        await self.terminate(step_id, "wall_clock")

    async def _silently(self, command: list[str]) -> None:
        with suppress(BaseException):
            process = await asyncio.create_subprocess_exec(
                executable(),
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            await asyncio.wait_for(process.wait(), TEARDOWN_TIMEOUT_SECONDS)
