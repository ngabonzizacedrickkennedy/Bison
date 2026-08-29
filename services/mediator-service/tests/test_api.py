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
from mediator_service.broker import BrokerClient
from mediator_service.config import settings
from mediator_service.persist import ProjectClient

PROJECT_ID = "prj_1"

BRIEF: dict[str, Any] = {
    "interpreted_goal": "Stand up a task tracker with a REST API",
    "project_type": "software",
    "summary": "A small tracker backed by SQLite",
    "known_constraints": ["No admin rights"],
    "assumptions": [],
    "out_of_scope": [],
    "seeded_success_criteria": ["The API answers on port 8000"],
}

BINDINGS = [
    {"role": "engine", "model_id": "anthropic/claude-sonnet-4"},
    {"role": "mediator", "model_id": "qwen2.5-coder:7b"},
]

APPROACH = "Create the schema, then the API."


def capability(backend: str | None, strength: str) -> dict[str, Any]:
    return {"backend": backend, "strength": strength, "available": [backend] if backend else []}


def manifest_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": "2026-08-29T09:00:00Z",
        "sandbox": capability("job_object", "medium"),
        "secrets": capability("keytar", "full"),
        "ocr": capability(None, "unavailable"),
        "database": capability("sqlite", "full"),
        "cache": capability("in_process", "medium"),
        "input_injection": capability("pyautogui", "verified"),
        "screen_capture": capability("mss", "full"),
        "hardware": {
            "os_version": "Windows 11 26100",
            "cpu_cores": 8,
            "ram_gb": 16,
            "free_disk_gb": 214.5,
        },
        "budgets": {"local_model_gb": 8, "max_projects": 5},
    }


def criterion(statement: str) -> dict[str, Any]:
    return {
        "statement": statement,
        "check_kind": "deterministic",
        "check_spec": {"type": "file_exists", "path": "schema.sql"},
        "weight": 1,
    }


def task(ref: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ref": ref,
        "parent_ref": None,
        "title": f"Task {ref}",
        "description": "",
        "kind": "code",
        "assigned_role": "engine",
        "depends_on": [],
        "criteria": [criterion(f"The file {ref}.sql is present")],
    }
    base.update(overrides)

    return base


def tree_json(*tasks: dict[str, Any]) -> str:
    entries = list(tasks) if tasks else [task("schema")]

    return json.dumps({"approach_summary": "Build it in two parts", "tasks": entries})


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("BISON_DATA_DIR", str(tmp_path))
    settings.cache_clear()
    (tmp_path / "capabilities.json").write_text(json.dumps(manifest_document()), encoding="utf-8")

    yield tmp_path

    settings.cache_clear()


@pytest.fixture(autouse=True)
def rested() -> Iterator[None]:
    api.halt_state.resume("test-setup")

    yield

    api.halt_state.resume("test-teardown")


class Upstream:
    def __init__(
        self,
        brief: dict[str, Any] | None = None,
        brief_status: int = 200,
        fail_task_on: int | None = None,
    ) -> None:
        self.brief = BRIEF if brief is None else brief
        self.brief_status = brief_status
        self.fail_task_on = fail_task_on
        self.tasks = 0
        self.criteria = 0
        self.sent: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.sent.append(path)

        if path.endswith("/brief"):
            if self.brief_status != 200:
                return httpx.Response(self.brief_status, json={"detail": "no brief"})

            return httpx.Response(200, json=self.brief)

        if path.endswith("/tasks"):
            self.tasks += 1

            if self.fail_task_on == self.tasks:
                return httpx.Response(409, json={"detail": "project is archived"})

            return httpx.Response(201, json={"id": f"tsk_{self.tasks}"})

        self.criteria += 1

        return httpx.Response(201, json={"id": f"crt_{self.criteria}"})


class Models:
    def __init__(self, *answers: str, bindings: list[dict[str, str]] | None = None) -> None:
        self.answers = list(answers)
        self.bindings = BINDINGS if bindings is None else bindings

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bindings"):
            return httpx.Response(200, json=self.bindings)

        if not self.answers:
            return httpx.Response(503, json={"detail": "no answers left"})

        return httpx.Response(200, json={"response": self.answers.pop(0)})


def wire(models: Models, upstream: Upstream) -> None:
    api.app.state.broker = BrokerClient(
        "http://127.0.0.1:8300", 30.0, 5.0, transport=httpx.MockTransport(models.handler)
    )
    api.app.state.projects = ProjectClient(
        "http://127.0.0.1:8400", 30.0, transport=httpx.MockTransport(upstream.handler)
    )
    api.app.state.upstream = httpx.AsyncClient(
        base_url="http://127.0.0.1:8400", transport=httpx.MockTransport(upstream.handler)
    )


async def call(models: Models, upstream: Upstream) -> httpx.Response:
    wire(models, upstream)
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/projects/{PROJECT_ID}/tree")


async def test_health_reports_where_it_talks_to() -> None:
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["boundary"] == "between_tasks"
    assert body["model_broker"].startswith("http")


async def test_a_tree_is_built_and_stored() -> None:
    response = await call(Models(APPROACH, tree_json()), Upstream())
    body = response.json()

    assert response.status_code == 200
    assert body["approach_summary"] == "Build it in two parts"
    assert body["attempts"] == 1
    assert body["repaired"] is False


async def test_the_response_maps_every_ref_to_its_real_id() -> None:
    tree = tree_json(task("schema"), task("api", depends_on=["schema"]))
    response = await call(Models(APPROACH, tree), Upstream())
    body = response.json()
    refs = {entry["ref"]: entry for entry in body["tasks"]}

    assert refs["schema"]["task_id"] == "tsk_1"
    assert refs["api"]["task_id"] == "tsk_2"
    assert refs["schema"]["criterion_ids"] == ["crt_1"]


async def test_the_execution_order_is_returned() -> None:
    tree = tree_json(task("schema"), task("api", depends_on=["schema"]))
    response = await call(Models(APPROACH, tree), Upstream())

    assert response.json()["execution_order"] == ["schema", "api"]


async def test_both_models_and_prompts_are_reported() -> None:
    response = await call(Models(APPROACH, tree_json()), Upstream())
    body = response.json()

    assert body["engine_model_id"] == "anthropic/claude-sonnet-4"
    assert body["mediator_model_id"] == "qwen2.5-coder:7b"
    assert body["engine_prompt"] == "engine.v1"
    assert body["mediator_prompt"] == "mediator.v1"


async def test_a_supplied_request_id_is_echoed() -> None:
    wire(Models(APPROACH, tree_json()), Upstream())
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/projects/{PROJECT_ID}/tree?request_id=req_9")

    assert response.json()["request_id"] == "req_9"


async def test_a_missing_request_id_is_generated() -> None:
    response = await call(Models(APPROACH, tree_json()), Upstream())

    assert len(response.json()["request_id"]) > 10


async def test_a_halted_mediator_refuses_to_start_a_tree() -> None:
    wire(Models(APPROACH, tree_json()), Upstream())
    api.halt_state.accept(
        HaltSignal(
            id="hlt_1",
            reason="kill_switch",
            project_id=PROJECT_ID,
            issued_at=datetime.now(UTC),
        )
    )
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/projects/{PROJECT_ID}/tree")

    assert response.status_code == 409
    assert response.json()["error"] == "halted"


async def test_a_project_with_no_brief_is_refused_rather_than_invented() -> None:
    response = await call(Models(APPROACH, tree_json()), Upstream(brief_status=404))

    assert response.status_code == 409
    assert response.json()["error"] == "no_brief"


async def test_a_brief_with_no_goal_is_refused() -> None:
    response = await call(
        Models(APPROACH, tree_json()), Upstream(brief={"project_type": "software"})
    )

    assert response.status_code == 409
    assert response.json()["error"] == "no_brief"


async def test_a_missing_manifest_is_reported_as_unavailable(data_dir: Path) -> None:
    (data_dir / "capabilities.json").unlink()

    response = await call(Models(APPROACH, tree_json()), Upstream())

    assert response.status_code == 503
    assert response.json()["error"] == "no_manifest"


async def test_a_tree_that_never_parses_is_reported() -> None:
    response = await call(Models(APPROACH, "not json", "still not json", "nope"), Upstream())

    assert response.status_code == 502
    assert response.json()["error"] == "tree_unparseable"


async def test_a_tree_that_stays_undisciplined_returns_its_findings() -> None:
    broken = tree_json(task("a", criteria=[criterion("The database is set up")]))
    response = await call(Models(APPROACH, broken, broken, broken), Upstream())
    body = response.json()

    assert response.status_code == 502
    assert body["error"] == "tree_rejected"
    assert body["findings"]


async def test_a_missing_binding_is_reported_as_a_broker_failure() -> None:
    models = Models(APPROACH, tree_json(), bindings=[BINDINGS[0]])
    response = await call(models, Upstream())

    assert response.status_code == 502
    assert response.json()["error"] == "broker_failed"


async def test_an_unreachable_broker_is_reported() -> None:
    class Dead(Models):
        def handler(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    response = await call(Dead(APPROACH, tree_json()), Upstream())

    assert response.status_code == 503
    assert response.json()["error"] == "broker_unreachable"


async def test_a_partial_write_reports_what_already_exists() -> None:
    tree = tree_json(task("schema"), task("api", depends_on=["schema"]))
    response = await call(Models(APPROACH, tree), Upstream(fail_task_on=2))
    body = response.json()

    assert response.status_code == 502
    assert body["error"] == "tree_partly_written"
    assert body["created"] == ["schema"]
    assert body["failed_ref"] == "api"


async def test_the_brief_is_read_before_any_model_is_called() -> None:
    upstream = Upstream(brief_status=404)

    await call(Models(), upstream)

    assert upstream.sent == [f"/projects/{PROJECT_ID}/brief"]
