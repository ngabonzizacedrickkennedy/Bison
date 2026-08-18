from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from wasmtime import wat2wasm

from task_runner_service import api
from task_runner_service.backends import Binding
from task_runner_service.sandbox import SandboxRequest
from task_runner_service.wasm import WasmSandbox

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the sandbox enforces Windows path containment"
)

SCOPE = r"C:\Users\x\bison\projects\demo"

PRINT = r"""(module
 (import "wasi_snapshot_preview1" "fd_write" (func $w (param i32 i32 i32 i32) (result i32)))
 (memory (export "memory") 1)
 (data (i32.const 100) "hello\n")
 (func (export "_start")
  (i32.store (i32.const 0) (i32.const 100))
  (i32.store (i32.const 4) (i32.const 6))
  (drop (call $w (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 20)))))"""


def effects(**overrides: object) -> dict[str, Any]:
    declared: dict[str, Any] = {
        "writes_paths": [],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    declared.update(overrides)

    return declared


def body(**overrides: object) -> dict[str, Any]:
    declared: dict[str, Any] = {
        "scope_root": SCOPE,
        "step": {"service": "task-runner", "effects": effects()},
        "confirmed": False,
        "program": "python",
        "arguments": ["-c", "pass"],
    }
    declared.update(overrides)

    return declared


def signal(reason: str = "kill_switch") -> dict[str, Any]:
    return {"id": "sig-1", "reason": reason, "issued_at": datetime.now(UTC).isoformat()}


class StubSandbox:
    def __init__(self) -> None:
        self.terminated: list[str] = []

    async def terminate_all(self, reason: str) -> list[str]:
        self.terminated.append(reason)

        return ["step-1"]


@pytest.fixture
def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=api.app), base_url="http://runner")


@pytest.fixture(autouse=True)
def clean_halt() -> Iterator[None]:
    api.halt_state.resume("test-setup")

    yield

    api.halt_state.resume("test-teardown")


@pytest.fixture
def scope_dir(tmp_path: Path) -> Path:
    directory = tmp_path.resolve() / "project"
    directory.mkdir()

    return directory


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "runs"


@pytest.fixture
def absent_data_dir(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "absent"


@pytest.fixture
def print_module(tmp_path: Path) -> Path:
    path = tmp_path.resolve() / "print.wasm"
    path.write_bytes(wat2wasm(PRINT))

    return path


async def test_health_reports_ok_when_not_halted(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/health")

    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["boundary"] == "immediate"
    assert payload["running"] == []


async def test_health_reports_halted_after_a_signal(client: AsyncClient) -> None:
    async with client:
        await client.post("/halt", json=signal())
        response = await client.get("/health")

    assert response.json()["status"] == "halted"


async def test_a_halt_terminates_running_steps(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubSandbox()
    monkeypatch.setattr(api.runner, "_sandboxes", {"job_object": stub})

    async with client:
        response = await client.post("/halt", json=signal())

    assert response.json()["boundary_meaning"].startswith("the process tree")
    assert stub.terminated == ["halt"]


async def test_sandboxes_report_what_they_enforce(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/sandboxes")

    reported = {entry["backend"]: entry for entry in response.json()}

    assert reported["wasm"]["network_isolation"]
    assert reported["wasm"]["accepts"] == ["wasm_module"]
    assert not reported["job_object"]["network_isolation"]
    assert not reported["job_object"]["filesystem_write_scope"]
    assert not reported["job_object"]["filesystem_read_scope"]


async def test_a_halted_runner_starts_no_work(client: AsyncClient) -> None:
    async with client:
        await client.post("/halt", json=signal())
        response = await client.post("/steps/step-1/run", json=body())

    assert response.status_code == 409
    assert "halted" in response.json()["detail"]


async def test_a_step_escaping_scope_is_refused(client: AsyncClient) -> None:
    step = {"service": "task-runner", "effects": effects(writes_paths=[r"C:\Windows\evil.txt"])}

    async with client:
        response = await client.post("/steps/step-1/run", json=body(step=step, confirmed=True))

    assert response.status_code == 403
    assert "outside the project directory" in response.json()["detail"]


async def test_an_unconfirmed_networked_step_is_refused(client: AsyncClient) -> None:
    step = {"service": "task-runner", "effects": effects(network=True)}

    async with client:
        response = await client.post("/steps/step-1/run", json=body(step=step))

    assert response.status_code == 403
    assert "reaches the network" in response.json()["detail"]


async def test_a_step_routed_elsewhere_is_refused(client: AsyncClient) -> None:
    step = {"service": "automation", "effects": effects()}

    async with client:
        response = await client.post("/steps/step-1/run", json=body(step=step, confirmed=True))

    assert response.status_code == 403


async def test_a_relative_scope_root_is_rejected(client: AsyncClient) -> None:
    async with client:
        response = await client.post("/steps/step-1/run", json=body(scope_root="demo"))

    assert response.status_code == 422


async def test_a_missing_manifest_reports_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, absent_data_dir: Path
) -> None:
    from task_runner_service import config

    monkeypatch.setenv("BISON_DATA_DIR", str(absent_data_dir))
    config.settings.cache_clear()

    async with client:
        response = await client.post("/steps/step-1/run", json=body())

    config.settings.cache_clear()

    assert response.status_code == 503
    assert "capability manifest" in response.json()["detail"]


async def test_a_run_streams_output_then_a_result(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    scope_dir: Path,
    runs_dir: Path,
    print_module: Path,
) -> None:
    sandbox = WasmSandbox(runtime_dir=runs_dir)
    binding = Binding(
        sandbox=sandbox, backend=sandbox.backend, preferred="wasm", degraded=False, reason=None
    )

    def planned(request: SandboxRequest) -> Binding:
        return binding

    monkeypatch.setattr(api.runner, "plan", planned)

    request = body(
        scope_root=str(scope_dir),
        program=str(print_module),
        arguments=[],
        working_directory=str(scope_dir),
    )

    async with client:
        response = await client.post("/steps/step-1/run", json=request)
        lines = [json.loads(line) for line in response.text.splitlines() if line]

    assert response.status_code == 200
    assert response.headers["x-bison-sandbox-backend"] == "wasm"
    assert response.headers["x-bison-sandbox-degraded"] == "false"
    assert lines[0]["event"] == "output"
    assert lines[0]["text"] == "hello\n"
    assert lines[-1]["event"] == "result"
    assert lines[-1]["exit_code"] == 0
    assert lines[-1]["backend"] == "wasm"


async def test_a_degraded_binding_is_announced_in_the_headers(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    scope_dir: Path,
    runs_dir: Path,
    print_module: Path,
) -> None:
    sandbox = WasmSandbox(runtime_dir=runs_dir)
    binding = Binding(
        sandbox=sandbox,
        backend=sandbox.backend,
        preferred="docker",
        degraded=True,
        reason="this machine prefers docker",
    )

    def planned(request: SandboxRequest) -> Binding:
        return binding

    monkeypatch.setattr(api.runner, "plan", planned)

    request = body(
        scope_root=str(scope_dir),
        program=str(print_module),
        arguments=[],
        working_directory=str(scope_dir),
    )

    async with client:
        response = await client.post("/steps/step-1/run", json=request)

    assert response.headers["x-bison-sandbox-degraded"] == "true"


async def test_terminating_an_unknown_step_reports_false(client: AsyncClient) -> None:
    async with client:
        response = await client.post("/steps/absent/terminate", json={"actor": "cedrick"})

    assert response.json() == {"terminated": False}
