from __future__ import annotations

import asyncio
import os
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows only")

if TYPE_CHECKING or sys.platform == "win32":
    from task_runner_service import integrity, ports, process
    from task_runner_service.jobobject import create_job, enrol

ENVIRONMENT_KEYS = ("SYSTEMROOT", "PATH", "TEMP")

SETTLE_SECONDS = 2.0

MEMORY_MB = 256


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        chosen: int = probe.getsockname()[1]

    return chosen


def environment() -> dict[str, str]:
    return {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ}


def listener(port: int, indirect: bool) -> str:
    bind = (
        "import socket, time\n"
        "s = socket.socket()\n"
        f"s.bind(('127.0.0.1', {port}))\n"
        "s.listen(1)\n"
        "time.sleep(30)\n"
    )

    if not indirect:
        return bind

    return (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {bind!r}])\n"
        "time.sleep(30)\n"
    )


async def watch(workspace: Path, source: str) -> list[int]:
    token = integrity.restricted_token()
    job = create_job(MEMORY_MB)
    launch = process.start(sys.executable, ["-c", source], workspace, environment(), token)
    watcher = ports.PortWatcher(launch.pid)

    try:
        enrol(job, launch.pid)
        process.resume(launch)
        watcher.start()

        await asyncio.sleep(SETTLE_SECONDS)

        await watcher.stop()

        return watcher.observed
    finally:
        with pytest.MonkeyPatch.context():
            pass

        import win32api
        import win32job

        win32job.TerminateJobObject(job, 1)
        process.close(launch)
        integrity.close(token)
        win32api.CloseHandle(job)


def test_an_empty_pid_set_observes_nothing() -> None:
    assert ports.listening(set()) == set()


def test_the_system_is_never_treated_as_a_step() -> None:
    assert ports.tree(0, set()) == set()


def test_a_known_pid_survives_a_later_sample() -> None:
    assert ports.tree(4242, {4242}) == {4242}


async def test_a_watcher_with_no_processes_observes_nothing() -> None:
    watcher = ports.PortWatcher(0)

    watcher.start()
    await asyncio.sleep(0.3)
    await watcher.stop()

    assert watcher.observed == []


async def test_a_port_opened_by_the_step_is_observed(workspace: Path) -> None:
    port = free_port()

    assert port in await watch(workspace, listener(port, indirect=False))


async def test_a_port_opened_by_a_grandchild_is_observed(workspace: Path) -> None:
    port = free_port()

    assert port in await watch(workspace, listener(port, indirect=True))


async def test_a_step_that_opens_nothing_observes_nothing(workspace: Path) -> None:
    assert await watch(workspace, "import time;time.sleep(2)") == []


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    directory = tmp_path.resolve() / "workspace"
    directory.mkdir()

    return directory
