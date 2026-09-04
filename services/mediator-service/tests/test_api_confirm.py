from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from bison_contracts.halt import HaltSignal

from mediator_service import api
from mediator_service.config import settings
from mediator_service.dispatch import RouterClient, RunnerClient
from mediator_service.execution import Clients
from mediator_service.upstream import ProjectClient as UpstreamProjectClient

PROJECT_ID = "prj_1"
TASK_ID = "tsk_1"
PLAN_ID = "pln_1"
STEP_ID = "stp_1"
NEXT_STEP_ID = "stp_2"
REQUEST_ID = "req_1"
SCOPE_ROOT = "C:\\scope"


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("BISON_DATA_DIR", str(tmp_path))
    settings.cache_clear()

    yield tmp_path

    settings.cache_clear()


@pytest.fixture(autouse=True)
def rested() -> Iterator[None]:
    api.halt_state.resume("test-setup")

    yield

    api.halt_state.resume("test-teardown")


def task_body(state: str = "awaiting_confirmation") -> dict[str, Any]:
    return {
        "id": TASK_ID,
        "parent_id": None,
        "title": "create the schema",
        "description": "write the schema file",
        "kind": "code",
        "state": state,
        "state_reason": None,
        "depends_on": [],
        "assigned_role": "engine",
        "position": 0,
    }


def stored_step_body(step_id: str, position: int, state: str, gated: bool) -> dict[str, Any]:
    return {
        "id": step_id,
        "plan_id": PLAN_ID,
        "position": position,
        "description": f"step {step_id}",
        "service": "task-runner",
        "action": {"type": "run_python_script", "script_path": "build.py", "arguments": []},
        "requires_confirmation": gated,
        "confirmation_reason": "it deletes files" if gated else None,
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": [],
        "effects": {
            "writes_paths": [],
            "deletes_paths": [],
            "network": False,
            "installs_packages": False,
            "needs_credentials": False,
            "drives_input": False,
            "reversible": True,
        },
        "state": state,
    }


def stored_plan_body(parked_state: str = "awaiting_confirmation") -> dict[str, Any]:
    return {
        "id": PLAN_ID,
        "project_id": PROJECT_ID,
        "task_id": TASK_ID,
        "request_id": REQUEST_ID,
        "scope_root": SCOPE_ROOT,
        "intent": "create the schema",
        "rationale": "the task asks for it",
        "steps": [
            stored_step_body(STEP_ID, 0, parked_state, True),
            stored_step_body(NEXT_STEP_ID, 1, "pending", False),
        ],
        "steps_total": 2,
        "gated_count": 1,
        "model_id": "qwen2.5-coder:7b",
        "prompt_name": "router",
        "prompt_version": "v4",
        "prompt_hash": "d9223d1149c4",
        "attempts": 1,
        "repaired": False,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def progress_body() -> dict[str, Any]:
    return {
        "overall": {
            "task_id": "__overall__",
            "percentage": 100.0,
            "criteria_total": 0,
            "criteria_verified": 0,
            "criteria_failed": 0,
            "criteria_ignored": 0,
        },
        "per_task": [],
    }


def run_stream(step_id: str) -> bytes:
    lines: list[dict[str, Any]] = [
        {
            "event": "output",
            "step_id": step_id,
            "stream": "stdout",
            "sequence": 0,
            "text": "building\n",
        },
        {
            "event": "result",
            "step_id": step_id,
            "backend": "job_object",
            "exit_code": 0,
            "terminated_by": None,
            "error_message": None,
            "files_written": [],
            "files_deleted": [],
            "files_written_total": 0,
            "files_deleted_total": 0,
            "files_truncated": False,
            "ports_opened": [],
            "output_bytes": 9,
            "output_truncated": False,
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": "2026-01-01T00:00:01+00:00",
        },
    ]

    return b"".join((json.dumps(entry) + "\n").encode("utf-8") for entry in lines)


class Project:
    def __init__(self, step_state: str = "awaiting_confirmation") -> None:
        self.step_state = step_state
        self.paths: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)

        if path.endswith("/progress"):
            return httpx.Response(200, json=progress_body())

        if path.endswith("/criteria"):
            return httpx.Response(200, json=[])

        if path.endswith("/tasks"):
            return httpx.Response(200, json=[task_body()])

        if path.endswith("/transitions"):
            return httpx.Response(200, json={"state": "succeeded"})

        if path.endswith("/state"):
            return httpx.Response(200, json=task_body("in_progress"))

        if path.startswith("/plans/"):
            return httpx.Response(200, json=stored_plan_body(self.step_state))

        if path.startswith("/steps/"):
            return httpx.Response(200, json=stored_step_body(STEP_ID, 0, self.step_state, True))

        return httpx.Response(404, json={"detail": f"no route for {path}"})


class Router:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url))

        return httpx.Response(500, json={"detail": "the router should not be asked"})


class Runner:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.bodies: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)

        parsed: Any = json.loads(request.content.decode("utf-8"))

        assert isinstance(parsed, dict)

        self.bodies.append(parsed)
        step: Any = parsed.get("step")
        step_id = step.get("step_id") if isinstance(step, dict) else STEP_ID

        return httpx.Response(
            200,
            content=run_stream(str(step_id)),
            headers={"content-type": "application/x-ndjson"},
        )

    def confirmations(self) -> list[bool]:
        return [entry["confirmed"] for entry in self.bodies]


def wire(monkeypatch: pytest.MonkeyPatch, project: Project, router: Router, runner: Runner) -> None:
    def build() -> Clients:
        return Clients(
            router=RouterClient(
                "http://127.0.0.1:8600", 30.0, 5.0, transport=httpx.MockTransport(router.handler)
            ),
            runner=RunnerClient(
                "http://127.0.0.1:8800", 30.0, 5.0, transport=httpx.MockTransport(runner.handler)
            ),
            project=UpstreamProjectClient(
                "http://127.0.0.1:8400", 30.0, transport=httpx.MockTransport(project.handler)
            ),
        )

    def reader() -> UpstreamProjectClient:
        return UpstreamProjectClient(
            "http://127.0.0.1:8400", 30.0, transport=httpx.MockTransport(project.handler)
        )

    monkeypatch.setattr(api, "clients_for_run", build)
    monkeypatch.setattr(api, "project_reader", reader)


async def call(step_id: str = STEP_ID) -> httpx.Response:
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/steps/{step_id}/confirm?request_id={REQUEST_ID}")


def events_of(response: httpx.Response) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


async def test_confirming_a_parked_step_streams_ndjson(monkeypatch: pytest.MonkeyPatch) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    response = await call()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")


async def test_the_confirmed_step_runs_without_asking_the_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = Router()
    runner = Runner()
    wire(monkeypatch, Project(), router, runner)

    await call()

    assert router.asked == []
    assert f"/steps/{STEP_ID}/run" in runner.paths


async def test_the_rest_of_the_plan_runs_after_the_confirmed_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Runner()
    wire(monkeypatch, Project(), Router(), runner)

    await call()

    assert runner.paths == [f"/steps/{STEP_ID}/run", f"/steps/{NEXT_STEP_ID}/run"]


async def test_only_the_confirmed_step_is_sent_as_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Runner()
    wire(monkeypatch, Project(), Router(), runner)

    await call()

    assert runner.confirmations() == [True, False]


async def test_the_stored_plan_is_read_back_rather_than_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project()
    wire(monkeypatch, project, Router(), Runner())

    await call()

    assert f"/steps/{STEP_ID}" in project.paths
    assert f"/plans/{PLAN_ID}" in project.paths


async def test_a_confirmed_run_walks_to_a_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    names = [entry["event"] for entry in events_of(await call())]

    assert names[0] == "run_started"
    assert names[-1] == "run_finished"
    assert "step_finished" in names


async def test_every_event_carries_the_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    events = events_of(await call())

    assert {entry["request_id"] for entry in events} == {REQUEST_ID}
    assert {entry["project_id"] for entry in events} == {PROJECT_ID}


async def test_a_step_that_is_not_parked_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    wire(monkeypatch, Project(step_state="succeeded"), Router(), Runner())

    response = await call()

    assert response.status_code == 409
    assert response.json()["error"] == "not_awaiting_confirmation"


async def test_a_refused_confirmation_starts_no_run(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Runner()
    wire(monkeypatch, Project(step_state="running"), Router(), runner)

    await call()

    assert runner.paths == []


async def test_the_refusal_names_the_state_it_found(monkeypatch: pytest.MonkeyPatch) -> None:
    wire(monkeypatch, Project(step_state="aborted"), Router(), Runner())

    assert "aborted" in (await call()).json()["detail"]


async def test_confirming_while_halted_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Runner()
    wire(monkeypatch, Project(), Router(), runner)
    api.halt_state.accept(HaltSignal(id="h-1", reason="kill_switch", issued_at=datetime.now(UTC)))

    response = await call()

    assert response.status_code == 409
    assert response.json()["error"] == "halted"
    assert runner.paths == []
