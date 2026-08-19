from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest

from task_runner_service import docker
from task_runner_service.docker import (
    TEMPORARY_GUEST_PATH,
    DockerSandbox,
    available,
    container_name,
    create_command,
    executable,
    guest_paths,
    mount_argument,
    translate,
)
from task_runner_service.sandbox import (
    InvalidSandboxRequestError,
    Limits,
    Mount,
    OutputChunk,
    ProgramKindUnsupportedError,
    SandboxRequest,
    SandboxUnavailableError,
    succeeded,
)

SCOPE = "C:\\bison\\project"

REFERENCE = "C:\\bison\\reference"

IMAGE = "python:3.12-slim"


class Recorder:
    def __init__(self) -> None:
        self.chunks: list[OutputChunk] = []

    async def emit(self, chunk: OutputChunk) -> None:
        self.chunks.append(chunk)

    def text(self, stream: str) -> str:
        return "".join(chunk.text for chunk in self.chunks if chunk.stream == stream)


class FakeProcess:
    def __init__(
        self,
        returncode: int | None,
        stdout: asyncio.StreamReader | None = None,
        stderr: asyncio.StreamReader | None = None,
        error: bytes = b"",
        release: asyncio.Event | None = None,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.killed = False
        self._error = error
        self._release = release

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._error

    async def wait(self) -> int | None:
        if self._release is not None:
            await self._release.wait()

        return self.returncode

    def kill(self) -> None:
        self.killed = True


class FakeDocker:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.stdout = b""
        self.stderr = b""
        self.exit_code: int | None = 0
        self.create_code = 0
        self.create_error = b""
        self.started = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def __call__(self, program: str, *arguments: str, **_: Any) -> FakeProcess:
        command = list(arguments)
        self.commands.append(command)

        if command[0] == "create":
            return FakeProcess(returncode=self.create_code, error=self.create_error)

        if command[0] == "start":
            self.started.set()

            return FakeProcess(
                returncode=self.exit_code,
                stdout=stream_of(self.stdout),
                stderr=stream_of(self.stderr),
                release=self.release,
            )

        return FakeProcess(returncode=0)

    def issued(self, verb: str) -> list[list[str]]:
        return [command for command in self.commands if command[0] == verb]


def stream_of(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()

    return reader


def build(**overrides: object) -> SandboxRequest:
    declared: dict[str, object] = {
        "step_id": "step-1",
        "program": "python",
        "arguments": ["script.py"],
        "working_directory": SCOPE,
        "mounts": [Mount(path=SCOPE, writable=True)],
        "environment": {},
        "network": False,
        "limits": Limits(wall_clock_seconds=30, memory_mb=256, max_output_bytes=65536),
    }
    declared.update(overrides)

    return SandboxRequest(**declared)  # type: ignore[arg-type]


def command_for(request: SandboxRequest) -> list[str]:
    return create_command(request, "bison-step", IMAGE, guest_paths(request))


def values(command: list[str], flag: str) -> list[str]:
    return [command[index + 1] for index, entry in enumerate(command) if entry == flag]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    recorder = FakeDocker()

    monkeypatch.setattr(docker, "executable", lambda: "docker")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)

    return recorder


@pytest.fixture
def sandbox(tmp_path: Path) -> DockerSandbox:
    return DockerSandbox(runtime_dir=tmp_path / "runs", image=IMAGE)


def test_the_backend_reports_what_it_enforces(sandbox: DockerSandbox) -> None:
    assert sandbox.backend == "docker"
    assert sandbox.accepts == frozenset({"native"})
    assert sandbox.enforcement.filesystem_write_scope
    assert sandbox.enforcement.filesystem_read_scope
    assert sandbox.enforcement.network_isolation
    assert sandbox.enforcement.memory_limit
    assert sandbox.enforcement.process_tree_kill


def test_availability_follows_the_docker_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert not available()

    with pytest.raises(SandboxUnavailableError):
        executable()


def test_a_container_name_is_legal_however_hostile_the_step_id() -> None:
    name = container_name("step/../weird id:9000")

    assert name.startswith("bison-")
    assert all(character.isalnum() or character in "-_." for character in name)


def test_the_primary_writable_mount_is_the_guest_workspace() -> None:
    mounts = [Mount(path=REFERENCE, writable=False), Mount(path=SCOPE, writable=True)]
    request = build(mounts=mounts)

    assert guest_paths(request) == [(mounts[1], "/workspace"), (mounts[0], "/mnt/0")]


def test_a_host_path_translates_into_the_guest_preserving_case() -> None:
    mapped = guest_paths(build())

    assert translate("C:\\bison\\project\\MyDir\\Run.py", mapped) == "/workspace/MyDir/Run.py"
    assert translate(SCOPE, mapped) == "/workspace"


def test_a_path_outside_every_mount_translates_to_nothing() -> None:
    assert translate("C:\\windows\\system32", guest_paths(build())) is None


def test_a_read_only_mount_is_bound_read_only() -> None:
    assert mount_argument(Mount(path=SCOPE, writable=True), "/workspace") == (
        f"type=bind,source={SCOPE},target=/workspace"
    )
    assert mount_argument(Mount(path=REFERENCE, writable=False), "/mnt/0") == (
        f"type=bind,source={REFERENCE},target=/mnt/0,readonly"
    )


def test_a_comma_in_a_mount_path_is_refused_rather_than_silently_split() -> None:
    with pytest.raises(InvalidSandboxRequestError):
        mount_argument(Mount(path="C:\\bison\\a,b", writable=True), "/workspace")


def test_the_container_is_isolated_limited_and_stripped() -> None:
    command = command_for(build())

    assert values(command, "--network") == ["none"]
    assert values(command, "--memory") == ["256m"]
    assert values(command, "--memory-swap") == ["256m"]
    assert values(command, "--pids-limit") == ["32"]
    assert values(command, "--cap-drop") == ["ALL"]
    assert values(command, "--security-opt") == ["no-new-privileges"]
    assert values(command, "--pull") == ["never"]
    assert "--read-only" in command
    assert values(command, "--tmpfs") == [TEMPORARY_GUEST_PATH]


def test_the_environment_is_passed_as_pairs_and_never_as_a_bare_key() -> None:
    command = command_for(build(environment={"TOKEN": "abc", "MODE": "test"}))

    assert values(command, "--env") == ["TOKEN=abc", "MODE=test"]
    assert all("=" in entry for entry in values(command, "--env"))


def test_an_empty_environment_declares_no_variables_at_all() -> None:
    assert values(command_for(build()), "--env") == []


def test_the_program_is_the_entrypoint_and_arguments_follow_the_image() -> None:
    command = command_for(build(arguments=["script.py", "--verbose"]))

    assert command[-4:] == ["python", IMAGE, "script.py", "--verbose"]


def test_the_working_directory_is_the_guest_path_not_the_host_path() -> None:
    command = command_for(build(working_directory="C:\\bison\\project\\src"))

    assert values(command, "--workdir") == ["/workspace/src"]


def test_a_working_directory_outside_every_mount_is_refused() -> None:
    with pytest.raises(InvalidSandboxRequestError):
        command_for(build(working_directory="C:\\bison\\elsewhere"))


def test_a_traversing_working_directory_is_refused_rather_than_normalised() -> None:
    with pytest.raises(InvalidSandboxRequestError):
        command_for(build(working_directory="C:\\bison\\project\\..\\windows"))


async def test_a_wasm_module_is_not_something_this_backend_runs(sandbox: DockerSandbox) -> None:
    with pytest.raises(ProgramKindUnsupportedError):
        await sandbox.run(build(program="module.wasm"), Recorder())


async def test_output_reaches_the_sink_tagged_with_the_step(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.stdout = b"counted 4 files\n"
    fake.stderr = b"a warning\n"

    recorder = Recorder()
    result = await sandbox.run(build(), recorder)

    assert recorder.text("stdout") == "counted 4 files\n"
    assert recorder.text("stderr") == "a warning\n"
    assert {chunk.step_id for chunk in recorder.chunks} == {"step-1"}
    assert succeeded(result)


async def test_the_exit_code_is_the_containers_own(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.exit_code = 3

    result = await sandbox.run(build(), Recorder())

    assert result.exit_code == 3
    assert result.terminated_by is None
    assert not succeeded(result)


async def test_a_stale_container_is_cleared_first_and_the_run_leaves_none_behind(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    await sandbox.run(build(), Recorder())

    removals = fake.issued("rm")

    assert len(removals) == 2
    assert all(command[-1] == container_name("step-1") for command in removals)


async def test_a_container_that_cannot_be_created_carries_dockers_own_words(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.create_code = 125
    fake.create_error = b"Error response from daemon: no such image"

    with pytest.raises(InvalidSandboxRequestError, match="no such image"):
        await sandbox.run(build(), Recorder())

    assert fake.issued("start") == []


async def test_a_create_that_never_answers_is_a_machine_problem(
    sandbox: DockerSandbox, fake: FakeDocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker, "CREATE_TIMEOUT_SECONDS", 0)

    with pytest.raises(SandboxUnavailableError):
        await sandbox.run(build(), Recorder())


async def test_a_halt_kills_the_container_and_masks_the_exit_code(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.release = asyncio.Event()

    running = asyncio.create_task(sandbox.run(build(), Recorder()))

    await fake.started.wait()

    assert await sandbox.terminate("step-1", "halt")

    fake.release.set()
    result = await running

    assert result.terminated_by == "halt"
    assert result.exit_code is None
    assert fake.issued("kill")[0] == ["kill", "--signal", "KILL", container_name("step-1")]


async def test_terminate_all_names_every_step_it_stopped(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.release = asyncio.Event()

    running = asyncio.create_task(sandbox.run(build(), Recorder()))

    await fake.started.wait()

    assert await sandbox.terminate_all("halt") == ["step-1"]

    fake.release.set()

    assert (await running).terminated_by == "halt"


async def test_terminating_a_step_that_is_not_running_reports_nothing_stopped(
    sandbox: DockerSandbox,
) -> None:
    assert not await sandbox.terminate("step-9", "step_abort")


async def test_the_same_step_cannot_run_twice_at_once(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.release = asyncio.Event()

    running = asyncio.create_task(sandbox.run(build(), Recorder()))

    await fake.started.wait()

    with pytest.raises(InvalidSandboxRequestError):
        await sandbox.run(build(), Recorder())

    fake.release.set()
    await running


async def test_output_beyond_the_limit_truncates_and_stops_the_container(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.stdout = b"0123456789"

    limits = Limits(wall_clock_seconds=30, memory_mb=256, max_output_bytes=4)
    result = await sandbox.run(build(limits=limits), Recorder())

    assert result.output_truncated
    assert result.output_bytes == 4
    assert result.terminated_by == "output_limit"
    assert fake.issued("kill")


async def test_a_step_outliving_its_wall_clock_is_stopped(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    fake.release = asyncio.Event()

    limits = Limits(wall_clock_seconds=1, memory_mb=256, max_output_bytes=65536)
    running = asyncio.create_task(sandbox.run(build(limits=limits), Recorder()))

    await fake.started.wait()
    await asyncio.sleep(1.2)

    fake.release.set()
    result = await running

    assert result.terminated_by == "wall_clock"
    assert result.exit_code is None


async def test_a_step_reports_no_ports_because_the_container_has_no_network(
    sandbox: DockerSandbox, fake: FakeDocker
) -> None:
    result = await sandbox.run(build(), Recorder())

    assert result.ports_opened == []
    assert result.backend == "docker"
