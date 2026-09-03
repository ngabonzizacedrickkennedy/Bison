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
STEP_ID = "stp_1"
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


def task_body(state: str = "ready") -> dict[str, Any]:
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


def plan_body() -> dict[str, Any]:
    return {
        "plan_id": "pln_1",
        "project_id": PROJECT_ID,
        "task_id": TASK_ID,
        "request_id": REQUEST_ID,
        "scope_root": SCOPE_ROOT,
        "intent": "create the schema",
        "rationale": "the task asks for it",
        "steps": [
            {
                "step_id": STEP_ID,
                "position": 0,
                "description": "run the build",
                "service": "task-runner",
                "action": {
                    "type": "run_python_script",
                    "script_path": "build.py",
                    "arguments": [],
                },
                "requires_confirmation": False,
                "confirmation_reason": None,
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
            }
        ],
        "steps_total": 1,
        "gated_count": 0,
        "model_id": "qwen2.5-coder:7b",
        "prompt_name": "router",
        "prompt_version": "v4",
        "prompt_hash": "d9223d1149c4",
        "attempts": 1,
        "repaired": False,
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


def run_stream() -> bytes:
    lines = [
        {
            "event": "output",
            "step_id": STEP_ID,
            "stream": "stdout",
            "sequence": 0,
            "text": "building\n",
        },
        {
            "event": "result",
            "step_id": STEP_ID,
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
    def __init__(self, task_state: str = "ready") -> None:
        self.task_state = task_state
        self.paths: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)

        if path.endswith("/progress"):
            return httpx.Response(200, json=progress_body())

        if path.endswith("/criteria"):
            return httpx.Response(200, json=[])

        if path.endswith("/tasks"):
            return httpx.Response(200, json=[task_body(self.task_state)])

        if path.endswith("/transitions"):
            return httpx.Response(200, json={"state": "succeeded"})

        if path.endswith("/state"):
            return httpx.Response(200, json=task_body())

        if path.endswith("/reconciliations"):
            return httpx.Response(201, json={"id": "rec_1"})

        return httpx.Response(404, json={"detail": f"no route for {path}"})


class Router:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url))

        return httpx.Response(200, json=plan_body())


class Runner:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)

        return httpx.Response(
            200, content=run_stream(), headers={"content-type": "application/x-ndjson"}
        )


class Watched(Clients):
    pass


class WatchedRouter(RouterClient):
    closed = False

    async def close(self) -> None:
        WatchedRouter.closed = True

        await super().close()


class WatchedRunner(RunnerClient):
    closed = False

    async def close(self) -> None:
        WatchedRunner.closed = True

        await super().close()


class WatchedProject(UpstreamProjectClient):
    closed = False

    async def close(self) -> None:
        WatchedProject.closed = True

        await super().close()


def wire(monkeypatch: pytest.MonkeyPatch, project: Project, router: Router, runner: Runner) -> None:
    WatchedRouter.closed = False
    WatchedRunner.closed = False
    WatchedProject.closed = False

    def build() -> Clients:
        return Clients(
            router=WatchedRouter(
                "http://127.0.0.1:8600", 30.0, 5.0, transport=httpx.MockTransport(router.handler)
            ),
            runner=WatchedRunner(
                "http://127.0.0.1:8800", 30.0, 5.0, transport=httpx.MockTransport(runner.handler)
            ),
            project=WatchedProject(
                "http://127.0.0.1:8400", 30.0, transport=httpx.MockTransport(project.handler)
            ),
        )

    monkeypatch.setattr(api, "clients_for_run", build)


async def call(query: str = f"?request_id={REQUEST_ID}") -> httpx.Response:
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/projects/{PROJECT_ID}/run{query}")


def events_of(response: httpx.Response) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


async def test_health_now_names_the_router_and_the_runner() -> None:
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    body = response.json()

    assert body["router_service"].startswith("http")
    assert body["task_runner"].startswith("http")


async def test_a_run_streams_ndjson(monkeypatch: pytest.MonkeyPatch) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    response = await call()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")


async def test_a_run_walks_from_start_to_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    names = [entry["event"] for entry in events_of(await call())]

    assert names[0] == "run_started"
    assert names[-1] == "run_finished"
    assert "step_output" in names
    assert "step_finished" in names


async def test_the_correlation_id_is_carried_on_every_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    events = events_of(await call())

    assert {entry["request_id"] for entry in events} == {REQUEST_ID}
    assert {entry["project_id"] for entry in events} == {PROJECT_ID}


async def test_a_run_without_a_correlation_id_invents_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    events = events_of(await call(query=""))
    given = {entry["request_id"] for entry in events}

    assert len(given) == 1
    assert given != {""}


async def test_the_router_is_asked_for_a_plan_for_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = Router()
    wire(monkeypatch, Project(), router, Runner())

    await call()

    assert f"/projects/{PROJECT_ID}/tasks/{TASK_ID}/plan" in router.asked[0]
    assert f"request_id={REQUEST_ID}" in router.asked[0]


async def test_the_step_is_sent_to_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Runner()
    wire(monkeypatch, Project(), Router(), runner)

    await call()

    assert runner.paths == [f"/steps/{STEP_ID}/run"]


async def test_the_task_is_carried_through_to_done(monkeypatch: pytest.MonkeyPatch) -> None:
    project = Project()
    wire(monkeypatch, project, Router(), Runner())

    events = events_of(await call())
    finished = [entry for entry in events if entry["event"] == "task_finished"]

    assert finished[0]["state"] == "completed"
    assert project.paths.count(f"/tasks/{TASK_ID}/state") == 3


async def test_every_client_is_closed_when_the_stream_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire(monkeypatch, Project(), Router(), Runner())

    await call()

    assert WatchedRouter.closed
    assert WatchedRunner.closed
    assert WatchedProject.closed


async def test_a_halted_service_refuses_to_start_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire(monkeypatch, Project(), Router(), Runner())
    api.halt_state.accept(HaltSignal(id="hlt_1", reason="kill_switch", issued_at=datetime.now(UTC)))

    response = await call()

    assert response.status_code == 409
    assert response.json()["error"] == "halted"
