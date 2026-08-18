from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from wasmtime import DirPerms, FilePerms, wat2wasm

from task_runner_service.sandbox import (
    InvalidSandboxRequestError,
    Limits,
    Mount,
    OutputChunk,
    ProgramKindUnsupportedError,
    SandboxRequest,
    succeeded,
)
from task_runner_service.wasm import WasmSandbox, guest_paths, permissions

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the sandbox enforces Windows path containment"
)

SILENT = r'(module (func (export "_start")))'

NO_START = r'(module (func (export "other")))'

SPIN = r'(module (func (export "_start") (loop $l br $l)))'

EXIT_THREE = r"""(module
 (import "wasi_snapshot_preview1" "proc_exit" (func $e (param i32)))
 (memory (export "memory") 1)
 (func (export "_start") i32.const 3 call $e))"""

PRINT = r"""(module
 (import "wasi_snapshot_preview1" "fd_write" (func $w (param i32 i32 i32 i32) (result i32)))
 (memory (export "memory") 1)
 (data (i32.const 100) "hello\n")
 (func (export "_start")
  (i32.store (i32.const 0) (i32.const 100))
  (i32.store (i32.const 4) (i32.const 6))
  (drop (call $w (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 20)))))"""

COMPLAIN = r"""(module
 (import "wasi_snapshot_preview1" "fd_write" (func $w (param i32 i32 i32 i32) (result i32)))
 (memory (export "memory") 1)
 (data (i32.const 100) "bad\n")
 (func (export "_start")
  (i32.store (i32.const 0) (i32.const 100))
  (i32.store (i32.const 4) (i32.const 4))
  (drop (call $w (i32.const 2) (i32.const 0) (i32.const 1) (i32.const 20)))))"""

FLOOD = r"""(module
 (import "wasi_snapshot_preview1" "fd_write" (func $w (param i32 i32 i32 i32) (result i32)))
 (memory (export "memory") 1)
 (data (i32.const 100) "0123456789")
 (func (export "_start")
  (i32.store (i32.const 0) (i32.const 100))
  (i32.store (i32.const 4) (i32.const 10))
  (loop $l
   (drop (call $w (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 20)))
   (br $l))))"""

WRITE_FILE = r"""(module
 (import "wasi_snapshot_preview1" "path_open"
  (func $o (param i32 i32 i32 i32 i32 i64 i64 i32 i32) (result i32)))
 (import "wasi_snapshot_preview1" "fd_write" (func $w (param i32 i32 i32 i32) (result i32)))
 (import "wasi_snapshot_preview1" "fd_close" (func $c (param i32) (result i32)))
 (memory (export "memory") 1)
 (data (i32.const 100) "out.txt")
 (data (i32.const 200) "written\n")
 (func (export "_start")
  (drop (call $o (i32.const 3) (i32.const 0) (i32.const 100) (i32.const 7) (i32.const 1)
                 (i64.const 536870911) (i64.const 536870911) (i32.const 0) (i32.const 12)))
  (i32.store (i32.const 0) (i32.const 200))
  (i32.store (i32.const 4) (i32.const 8))
  (drop (call $w (i32.load (i32.const 12)) (i32.const 0) (i32.const 1) (i32.const 8)))
  (drop (call $c (i32.load (i32.const 12))))))"""


class Recorder:
    def __init__(self) -> None:
        self.chunks: list[OutputChunk] = []

    async def emit(self, chunk: OutputChunk) -> None:
        self.chunks.append(chunk)

    def text(self, stream: str) -> str:
        return "".join(chunk.text for chunk in self.chunks if chunk.stream == stream)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    directory = tmp_path.resolve() / "workspace"
    directory.mkdir()

    return directory


@pytest.fixture
def sandbox(tmp_path: Path) -> WasmSandbox:
    return WasmSandbox(runtime_dir=tmp_path.resolve() / "runs")


def compile_module(tmp_path: Path, name: str, source: str) -> Path:
    directory = tmp_path.resolve() / "bin"
    directory.mkdir(exist_ok=True)
    path = directory / f"{name}.wasm"
    path.write_bytes(wat2wasm(source))

    return path


def missing_module(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "bin" / "absent.wasm"


def build(program: Path, workspace: Path, **overrides: object) -> SandboxRequest:
    declared: dict[str, object] = {
        "step_id": "step-1",
        "program": str(program),
        "arguments": [],
        "working_directory": str(workspace),
        "mounts": [Mount(path=str(workspace), writable=True)],
        "environment": {},
        "network": False,
        "limits": Limits(wall_clock_seconds=30, memory_mb=64, max_output_bytes=65536),
    }
    declared.update(overrides)

    return SandboxRequest(**declared)  # type: ignore[arg-type]


def test_the_primary_writable_mount_is_the_guest_root(workspace: Path, tmp_path: Path) -> None:
    reference = tmp_path.resolve() / "reference"
    mounts = [Mount(path=str(reference), writable=False), Mount(path=str(workspace), writable=True)]
    request = build(Path("m.wasm"), workspace, mounts=mounts)

    assert guest_paths(request) == [(mounts[1], "/"), (mounts[0], "/mnt/0")]


def test_read_only_mounts_map_to_read_only_permissions() -> None:
    assert permissions(Mount(path="C:\\a", writable=True)) == (
        DirPerms.READ_WRITE,
        FilePerms.READ_WRITE,
    )
    assert permissions(Mount(path="C:\\a", writable=False)) == (
        DirPerms.READ_ONLY,
        FilePerms.READ_ONLY,
    )


def test_the_backend_reports_what_it_enforces(sandbox: WasmSandbox) -> None:
    assert sandbox.backend == "wasm"
    assert sandbox.accepts == frozenset({"wasm_module"})
    assert sandbox.enforcement.network_isolation
    assert sandbox.enforcement.process_tree_kill


async def test_a_module_that_returns_reports_a_zero_exit(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "silent", SILENT)

    result = await sandbox.run(build(program, workspace), Recorder())

    assert succeeded(result)
    assert result.exit_code == 0
    assert result.terminated_by is None
    assert result.error_message is None
    assert result.backend == "wasm"


async def test_a_module_that_exits_reports_its_status(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "exit", EXIT_THREE)

    result = await sandbox.run(build(program, workspace), Recorder())

    assert result.exit_code == 3
    assert not succeeded(result)


async def test_a_module_without_an_entry_point_reports_an_error(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "nostart", NO_START)

    result = await sandbox.run(build(program, workspace), Recorder())

    assert result.exit_code is None
    assert result.error_message is not None
    assert "_start" in result.error_message


async def test_stdout_is_streamed(sandbox: WasmSandbox, workspace: Path, tmp_path: Path) -> None:
    program = compile_module(tmp_path, "print", PRINT)
    recorder = Recorder()

    result = await sandbox.run(build(program, workspace), recorder)

    assert recorder.text("stdout") == "hello\n"
    assert result.output_bytes == 6
    assert not result.output_truncated


async def test_stderr_is_streamed_separately(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "complain", COMPLAIN)
    recorder = Recorder()

    await sandbox.run(build(program, workspace), recorder)

    assert recorder.text("stderr") == "bad\n"
    assert recorder.text("stdout") == ""


async def test_a_written_file_is_hashed_and_reported(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "writefile", WRITE_FILE)

    result = await sandbox.run(build(program, workspace), Recorder())

    assert [Path(entry.path).name for entry in result.files_written] == ["out.txt"]
    assert result.files_written[0].size_bytes == 8
    assert len(result.files_written[0].sha256) == 64
    assert result.files_deleted == []


async def test_an_untouched_workspace_reports_no_files(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "silent", SILENT)
    (workspace / "existing.txt").write_bytes(b"kept")

    result = await sandbox.run(build(program, workspace), Recorder())

    assert result.files_written == []
    assert result.files_deleted == []


async def test_the_wall_clock_limit_terminates_a_spinning_module(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "spin", SPIN)
    limits = Limits(wall_clock_seconds=1, memory_mb=64, max_output_bytes=65536)

    result = await sandbox.run(build(program, workspace, limits=limits), Recorder())

    assert result.terminated_by == "wall_clock"
    assert result.exit_code is None
    assert not succeeded(result)


async def test_terminate_stops_a_running_module(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "spin", SPIN)
    running = asyncio.create_task(sandbox.run(build(program, workspace), Recorder()))

    await asyncio.sleep(0.3)

    assert await sandbox.terminate("step-1", "halt")

    result = await running

    assert result.terminated_by == "halt"


async def test_terminate_all_stops_a_running_module(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "spin", SPIN)
    running = asyncio.create_task(sandbox.run(build(program, workspace), Recorder()))

    await asyncio.sleep(0.3)

    assert await sandbox.terminate_all("halt") == ["step-1"]

    assert (await running).terminated_by == "halt"


async def test_terminating_an_unknown_step_reports_false(sandbox: WasmSandbox) -> None:
    assert not await sandbox.terminate("absent", "halt")
    assert await sandbox.terminate_all("halt") == []


async def test_runaway_output_is_cut_and_terminated(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "flood", FLOOD)
    limits = Limits(wall_clock_seconds=20, memory_mb=64, max_output_bytes=256)

    result = await sandbox.run(build(program, workspace, limits=limits), Recorder())

    assert result.output_truncated
    assert result.output_bytes == 256
    assert result.terminated_by == "output_limit"


async def test_a_native_program_is_refused(sandbox: WasmSandbox, workspace: Path) -> None:
    with pytest.raises(ProgramKindUnsupportedError):
        await sandbox.run(build(Path("python.exe"), workspace), Recorder())


async def test_a_missing_module_is_refused(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    absent = missing_module(tmp_path)

    with pytest.raises(InvalidSandboxRequestError, match="no module exists"):
        await sandbox.run(build(absent, workspace), Recorder())


async def test_a_step_cannot_run_twice_at_once(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "spin", SPIN)
    running = asyncio.create_task(sandbox.run(build(program, workspace), Recorder()))

    await asyncio.sleep(0.3)

    with pytest.raises(InvalidSandboxRequestError, match="already running"):
        await sandbox.run(build(program, workspace), Recorder())

    await sandbox.terminate("step-1", "halt")
    await running


async def test_a_step_may_run_again_after_it_finishes(
    sandbox: WasmSandbox, workspace: Path, tmp_path: Path
) -> None:
    program = compile_module(tmp_path, "silent", SILENT)

    assert succeeded(await sandbox.run(build(program, workspace), Recorder()))
    assert succeeded(await sandbox.run(build(program, workspace), Recorder()))
