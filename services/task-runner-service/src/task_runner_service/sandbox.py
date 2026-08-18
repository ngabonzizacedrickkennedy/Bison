from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from bison_contracts import SandboxBackend

from task_runner_service.scope import ScopeRootError, contained, root_segments

OutputStream = Literal["stdout", "stderr"]

Termination = Literal["halt", "step_abort", "wall_clock", "memory", "output_limit"]

ProgramKind = Literal["wasm_module", "native"]

MAX_ENVIRONMENT_KEYS = 64


class InvalidSandboxRequestError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class SandboxUnavailableError(RuntimeError):
    def __init__(self, backend: str, detail: str) -> None:
        super().__init__(f"the {backend} sandbox is unavailable: {detail}")
        self.backend = backend
        self.detail = detail


class ProgramKindUnsupportedError(RuntimeError):
    def __init__(self, backend: str, kind: ProgramKind) -> None:
        super().__init__(f"the {backend} sandbox cannot run a {kind} program")
        self.backend = backend
        self.kind = kind


@dataclass(frozen=True)
class Mount:
    path: str
    writable: bool


@dataclass(frozen=True)
class Limits:
    wall_clock_seconds: int
    memory_mb: int
    max_output_bytes: int


@dataclass(frozen=True)
class Enforcement:
    filesystem_write_scope: bool
    filesystem_read_scope: bool
    network_isolation: bool
    memory_limit: bool
    process_tree_kill: bool


@dataclass(frozen=True)
class SandboxRequest:
    step_id: str
    program: str
    arguments: list[str]
    working_directory: str
    mounts: list[Mount]
    environment: dict[str, str]
    network: bool
    limits: Limits


@dataclass(frozen=True)
class OutputChunk:
    step_id: str
    stream: OutputStream
    sequence: int
    text: str


@dataclass(frozen=True)
class FileEffect:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SandboxResult:
    step_id: str
    backend: SandboxBackend
    exit_code: int | None
    terminated_by: Termination | None
    error_message: str | None
    files_written: list[FileEffect]
    files_deleted: list[str]
    files_written_total: int
    files_deleted_total: int
    files_truncated: bool
    ports_opened: list[int]
    output_bytes: int
    output_truncated: bool
    started_at: datetime
    ended_at: datetime


class OutputSink(Protocol):
    async def emit(self, chunk: OutputChunk) -> None: ...


class Sandbox(Protocol):
    @property
    def backend(self) -> SandboxBackend: ...

    @property
    def enforcement(self) -> Enforcement: ...

    @property
    def accepts(self) -> frozenset[ProgramKind]: ...

    async def run(self, request: SandboxRequest, sink: OutputSink) -> SandboxResult: ...

    async def terminate(self, step_id: str, reason: Termination) -> bool: ...

    async def terminate_all(self, reason: Termination) -> list[str]: ...


def succeeded(result: SandboxResult) -> bool:
    return result.exit_code == 0 and result.terminated_by is None


def program_kind(request: SandboxRequest) -> ProgramKind:
    return "wasm_module" if request.program.lower().endswith(".wasm") else "native"


def writable_mounts(request: SandboxRequest) -> list[Mount]:
    return [mount for mount in request.mounts if mount.writable]


def assert_valid(request: SandboxRequest) -> None:
    if not request.step_id:
        raise InvalidSandboxRequestError("a sandbox request must name the step it belongs to")

    if not request.program:
        raise InvalidSandboxRequestError("a sandbox request must name a program to run")

    if not request.mounts:
        raise InvalidSandboxRequestError("a sandbox request must declare at least one mount")

    writable = writable_mounts(request)

    if not writable:
        raise InvalidSandboxRequestError("a sandbox request must declare one writable mount")

    for mount in request.mounts:
        try:
            root_segments(mount.path)
        except ScopeRootError as error:
            raise InvalidSandboxRequestError(
                f"mount {mount.path!r} is not an absolute path"
            ) from error

    if not any(contained(request.working_directory, root_segments(m.path)) for m in writable):
        raise InvalidSandboxRequestError(
            f"the working directory {request.working_directory!r} lies outside every writable mount"
        )

    limits = request.limits

    if limits.wall_clock_seconds <= 0 or limits.memory_mb <= 0 or limits.max_output_bytes <= 0:
        raise InvalidSandboxRequestError("every sandbox limit must be a positive value")

    if len(request.environment) > MAX_ENVIRONMENT_KEYS:
        raise InvalidSandboxRequestError(
            f"a sandbox request may declare at most {MAX_ENVIRONMENT_KEYS} environment variables"
        )

    for key in request.environment:
        if not key or "=" in key or key != key.strip():
            raise InvalidSandboxRequestError(f"environment variable name {key!r} is not usable")
