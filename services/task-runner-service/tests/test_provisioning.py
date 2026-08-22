from __future__ import annotations

import sys
from pathlib import Path

import pytest
from bison_contracts import SandboxBackend

from task_runner_service import venvs
from task_runner_service.backends import Binding
from task_runner_service.execution import Runner, build_request
from task_runner_service.sandbox import (
    Enforcement,
    OutputSink,
    ProgramKind,
    SandboxRequest,
    SandboxResult,
    Termination,
)


class Stub:
    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    @property
    def backend(self) -> SandboxBackend:
        return self._backend

    @property
    def enforcement(self) -> Enforcement:
        return Enforcement(
            filesystem_write_scope=False,
            filesystem_read_scope=False,
            network_isolation=False,
            memory_limit=False,
            process_tree_kill=False,
        )

    @property
    def accepts(self) -> frozenset[ProgramKind]:
        return frozenset({"native"})

    async def run(self, request: SandboxRequest, sink: OutputSink) -> SandboxResult:
        raise NotImplementedError

    async def terminate(self, step_id: str, reason: Termination) -> bool:
        return False

    async def terminate_all(self, reason: Termination) -> list[str]:
        return []


def binding_for(backend: str) -> Binding:
    chosen = SandboxBackend(backend)

    return Binding(
        sandbox=Stub(chosen),
        backend=chosen,
        preferred=backend,
        degraded=False,
        reason=None,
    )


HOST = binding_for("job_object")

CONTAINER = binding_for("docker")


@pytest.fixture
def runtime(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "runs"


@pytest.fixture
def scope(tmp_path: Path) -> str:
    directory = tmp_path.resolve() / "scope"
    directory.mkdir()

    return str(directory)


def native(scope: str, program: str = "python") -> SandboxRequest:
    return build_request("step-1", {"program": program, "arguments": ["-c", "pass"]}, scope)


async def test_a_native_step_is_given_an_environment(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)

    provisioned = await runner.provision(native(scope), "task-1", HOST)

    assert Path(provisioned.program) == venvs.interpreter(venvs.home(runtime, "task-1"))


async def test_the_machine_interpreter_is_replaced(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)

    provisioned = await runner.provision(native(scope, sys.executable), "task-1", HOST)

    assert Path(provisioned.program) != Path(sys.executable)


async def test_a_step_that_is_not_python_keeps_its_program(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)

    provisioned = await runner.provision(native(scope, "git"), "task-1", HOST)

    assert provisioned.program == "git"


async def test_the_environment_is_placed_on_the_path(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)

    provisioned = await runner.provision(native(scope), "task-1", HOST)
    venv = venvs.home(runtime, "task-1")

    assert provisioned.environment["VIRTUAL_ENV"] == str(venv)
    assert provisioned.environment["PATH"].startswith(str(venv / venvs.BIN_DIRECTORY))


async def test_two_steps_of_one_task_share_an_environment(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)

    first = await runner.provision(native(scope), "task-1", HOST)
    second = await runner.provision(native(scope), "task-1", HOST)

    assert first.program == second.program


async def test_two_tasks_do_not_share_an_environment(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)

    first = await runner.provision(native(scope), "task-1", HOST)
    second = await runner.provision(native(scope), "task-2", HOST)

    assert first.program != second.program


async def test_a_wasm_step_is_left_untouched(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)
    request = build_request("step-1", {"program": "module.wasm"}, scope)

    provisioned = await runner.provision(request, "task-1", HOST)

    assert provisioned is request
    assert not venvs.home(runtime, "task-1").exists()


async def test_the_original_request_is_not_mutated(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)
    request = native(scope)

    await runner.provision(request, "task-1", HOST)

    assert request.program == "python"


async def test_a_container_step_keeps_the_program_it_was_given(runtime: Path, scope: str) -> None:
    runner = Runner(runtime)
    request = native(scope)

    provisioned = await runner.provision(request, "task-1", CONTAINER)

    assert provisioned is request
    assert provisioned.program == "python"


async def test_a_container_step_builds_no_environment_on_the_host(
    runtime: Path, scope: str
) -> None:
    runner = Runner(runtime)

    provisioned = await runner.provision(native(scope), "task-1", CONTAINER)

    assert "VIRTUAL_ENV" not in provisioned.environment
    assert not venvs.home(runtime, "task-1").exists()
