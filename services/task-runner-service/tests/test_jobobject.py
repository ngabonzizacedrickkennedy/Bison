from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from task_runner_service.sandbox import (
    InvalidSandboxRequestError,
    Limits,
    Mount,
    OutputChunk,
    ProgramKindUnsupportedError,
    SandboxRequest,
    succeeded,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows only")

if TYPE_CHECKING or sys.platform == "win32":
    from task_runner_service.jobobject import JobObjectSandbox

ENVIRONMENT_KEYS = ("SYSTEMROOT", "PATH", "TEMP")


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
def sandbox(tmp_path: Path) -> JobObjectSandbox:
    return JobObjectSandbox(runtime_dir=tmp_path.resolve() / "runs")


def environment() -> dict[str, str]:
    return {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ}


def script(workspace: Path, name: str, body: str) -> str:
    path = workspace / f"{name}.py"
    path.write_text(body, encoding="utf-8")

    return f"{name}.py"


def build(workspace: Path, arguments: list[str], **overrides: object) -> SandboxRequest:
    declared: dict[str, object] = {
        "step_id": "step-1",
        "program": sys.executable,
        "arguments": arguments,
        "working_directory": str(workspace),
        "mounts": [Mount(path=str(workspace), writable=True)],
        "environment": environment(),
        "network": False,
        "limits": Limits(wall_clock_seconds=30, memory_mb=256, max_output_bytes=65536),
    }
    declared.update(overrides)

    return SandboxRequest(**declared)  # type: ignore[arg-type]


def test_the_backend_reports_what_it_does_not_enforce(sandbox: JobObjectSandbox) -> None:
    assert sandbox.backend == "job_object"
    assert sandbox.accepts == frozenset({"native"})
    assert sandbox.enforcement.process_tree_kill
    assert sandbox.enforcement.memory_limit
    assert not sandbox.enforcement.filesystem_scope
    assert not sandbox.enforcement.network_isolation


async def test_a_process_that_returns_reports_a_zero_exit(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    result = await sandbox.run(build(workspace, ["-c", "pass"]), Recorder())

    assert succeeded(result)
    assert result.exit_code == 0
    assert result.terminated_by is None
    assert result.backend == "job_object"


async def test_a_process_that_exits_reports_its_status(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    result = await sandbox.run(build(workspace, ["-c", "raise SystemExit(3)"]), Recorder())

    assert result.exit_code == 3
    assert not succeeded(result)


async def test_stdout_is_streamed(sandbox: JobObjectSandbox, workspace: Path) -> None:
    recorder = Recorder()

    await sandbox.run(build(workspace, ["-c", "print('hello')"]), recorder)

    assert recorder.text("stdout").strip() == "hello"
    assert recorder.text("stderr") == ""


async def test_stderr_is_streamed_separately(sandbox: JobObjectSandbox, workspace: Path) -> None:
    recorder = Recorder()
    body = "import sys; sys.stderr.write('bad')"

    await sandbox.run(build(workspace, ["-c", body]), recorder)

    assert recorder.text("stderr") == "bad"
    assert recorder.text("stdout") == ""


async def test_a_written_file_is_hashed_and_reported(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    body = "open('out.txt', 'w').write('written')"

    result = await sandbox.run(build(workspace, ["-c", body]), Recorder())

    assert [Path(entry.path).name for entry in result.files_written] == ["out.txt"]
    assert result.files_written[0].size_bytes == 7
    assert result.files_deleted == []


async def test_a_deleted_file_is_reported(sandbox: JobObjectSandbox, workspace: Path) -> None:
    (workspace / "doomed.txt").write_bytes(b"here")
    body = "import os; os.remove('doomed.txt')"

    result = await sandbox.run(build(workspace, ["-c", body]), Recorder())

    assert [Path(path).name for path in result.files_deleted] == ["doomed.txt"]
    assert result.files_written == []


async def test_the_process_runs_in_the_working_directory(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    recorder = Recorder()
    body = "import os; print(os.getcwd())"

    await sandbox.run(build(workspace, ["-c", body]), recorder)

    assert Path(recorder.text("stdout").strip()) == workspace


async def test_the_environment_is_not_inherited(
    sandbox: JobObjectSandbox, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BISON_SECRET_FOR_TEST", "leaked")
    recorder = Recorder()
    body = "import os; print(os.environ.get('BISON_SECRET_FOR_TEST', 'absent'))"

    await sandbox.run(build(workspace, ["-c", body]), recorder)

    assert recorder.text("stdout").strip() == "absent"


async def test_the_wall_clock_limit_terminates_a_sleeping_process(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    limits = Limits(wall_clock_seconds=1, memory_mb=256, max_output_bytes=65536)
    body = "import time; time.sleep(30)"

    result = await sandbox.run(build(workspace, ["-c", body], limits=limits), Recorder())

    assert result.terminated_by == "wall_clock"
    assert result.exit_code is None


async def test_terminate_stops_a_running_process(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    body = "import time; time.sleep(30)"
    running = asyncio.create_task(sandbox.run(build(workspace, ["-c", body]), Recorder()))

    await asyncio.sleep(0.5)

    assert await sandbox.terminate("step-1", "halt")

    assert (await running).terminated_by == "halt"


async def test_terminate_all_stops_a_running_process(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    body = "import time; time.sleep(30)"
    running = asyncio.create_task(sandbox.run(build(workspace, ["-c", body]), Recorder()))

    await asyncio.sleep(0.5)

    assert await sandbox.terminate_all("halt") == ["step-1"]

    assert (await running).terminated_by == "halt"


async def test_the_whole_process_tree_dies(sandbox: JobObjectSandbox, workspace: Path) -> None:
    script(workspace, "child", "import time\ntime.sleep(2)\nopen('child.txt', 'w').write('x')\n")
    parent = script(
        workspace,
        "parent",
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "time.sleep(30)\n",
    )

    running = asyncio.create_task(sandbox.run(build(workspace, [parent]), Recorder()))

    await asyncio.sleep(0.8)
    await sandbox.terminate("step-1", "halt")

    assert (await running).terminated_by == "halt"

    await asyncio.sleep(2.5)

    assert not (workspace / "child.txt").exists()


async def test_terminating_an_unknown_step_reports_false(sandbox: JobObjectSandbox) -> None:
    assert not await sandbox.terminate("absent", "halt")
    assert await sandbox.terminate_all("halt") == []


async def test_runaway_output_is_cut_and_terminated(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    limits = Limits(wall_clock_seconds=20, memory_mb=256, max_output_bytes=256)
    body = "while True: print('0123456789')"

    result = await sandbox.run(build(workspace, ["-c", body], limits=limits), Recorder())

    assert result.output_truncated
    assert result.output_bytes == 256
    assert result.terminated_by == "output_limit"


async def test_a_wasm_module_is_refused(sandbox: JobObjectSandbox, workspace: Path) -> None:
    with pytest.raises(ProgramKindUnsupportedError):
        await sandbox.run(build(workspace, [], program=str(workspace / "m.wasm")), Recorder())


async def test_a_missing_program_is_refused(sandbox: JobObjectSandbox, workspace: Path) -> None:
    absent = str(workspace / "absent.exe")

    with pytest.raises(InvalidSandboxRequestError, match="could not be started"):
        await sandbox.run(build(workspace, [], program=absent), Recorder())


async def test_a_step_cannot_run_twice_at_once(sandbox: JobObjectSandbox, workspace: Path) -> None:
    body = "import time; time.sleep(30)"
    running = asyncio.create_task(sandbox.run(build(workspace, ["-c", body]), Recorder()))

    await asyncio.sleep(0.5)

    with pytest.raises(InvalidSandboxRequestError, match="already running"):
        await sandbox.run(build(workspace, ["-c", body]), Recorder())

    await sandbox.terminate("step-1", "halt")
    await running


async def test_a_step_may_run_again_after_it_finishes(
    sandbox: JobObjectSandbox, workspace: Path
) -> None:
    assert succeeded(await sandbox.run(build(workspace, ["-c", "pass"]), Recorder()))
    assert succeeded(await sandbox.run(build(workspace, ["-c", "pass"]), Recorder()))
