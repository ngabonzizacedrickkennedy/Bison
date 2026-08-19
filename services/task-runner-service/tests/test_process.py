from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="this launcher is Windows only")

if TYPE_CHECKING or sys.platform == "win32":
    from task_runner_service import integrity, process

ENVIRONMENT_KEYS = ("SYSTEMROOT", "PATH", "TEMP")

STILL_ACTIVE = 259


def base_environment() -> dict[str, str]:
    return {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path.resolve()


async def collect(handle: int) -> str:
    chunks: list[bytes] = []

    while data := await process.read(handle):
        chunks.append(data)

    return b"".join(chunks).decode("utf-8", "replace")


async def run(
    source: str,
    working_directory: Path,
    environment: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    token = integrity.restricted_token()
    launch = process.start(
        sys.executable,
        ["-c", source],
        working_directory,
        environment if environment is not None else base_environment(),
        token,
    )

    try:
        process.resume(launch)

        out, err = await asyncio.gather(collect(launch.stdout), collect(launch.stderr))
        code = await process.wait(launch)

        return out, err, code
    finally:
        process.close(launch)
        integrity.close(token)


async def test_a_launched_process_does_not_run_until_resumed(workspace: Path) -> None:
    import win32process

    token = integrity.restricted_token()
    launch = process.start(
        sys.executable, ["-c", "print('ran')"], workspace, base_environment(), token
    )

    try:
        await asyncio.sleep(0.3)

        assert win32process.GetExitCodeProcess(launch.process) == STILL_ACTIVE

        process.resume(launch)

        assert (await collect(launch.stdout)).strip() == "ran"
        assert await process.wait(launch) == 0
    finally:
        process.close(launch)
        integrity.close(token)


async def test_stdout_is_captured(workspace: Path) -> None:
    out, err, code = await run("print('hello')", workspace)

    assert out.strip() == "hello"
    assert err == ""
    assert code == 0


async def test_stderr_is_captured(workspace: Path) -> None:
    out, err, code = await run("import sys;sys.stderr.write('broken')", workspace)

    assert out == ""
    assert err.strip() == "broken"
    assert code == 0


async def test_the_exit_code_is_reported(workspace: Path) -> None:
    _out, _err, code = await run("raise SystemExit(7)", workspace)

    assert code == 7


async def test_output_larger_than_the_pipe_buffer_is_read_whole(workspace: Path) -> None:
    out, _err, code = await run("print('x' * 300000)", workspace)

    assert len(out.strip()) == 300000
    assert code == 0


async def test_the_environment_is_exactly_what_was_given(workspace: Path) -> None:
    environment = base_environment() | {"BISON_PROBE": "present"}
    source = "import os;print(os.environ.get('BISON_PROBE'));print('USERNAME' in os.environ)"

    out, _err, code = await run(source, workspace, environment)

    assert out.splitlines() == ["present", "False"]
    assert code == 0


async def test_the_working_directory_is_honoured(workspace: Path) -> None:
    out, _err, code = await run("import os;print(os.getcwd())", workspace)

    assert Path(out.strip()) == workspace
    assert code == 0


async def test_a_process_that_writes_nothing_reads_as_empty(workspace: Path) -> None:
    out, err, code = await run("pass", workspace)

    assert out == ""
    assert err == ""
    assert code == 0
