from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service.persist import ProjectServiceError, ProjectServiceUnreachableError
from mediator_service.upstream import (
    ACTOR,
    Outcome,
    ProjectClient,
    Snapshot,
    to_criterion,
    to_progress,
    to_snapshot,
    to_task,
)

BASE_URL = "http://project.test"

SPEC: dict[str, Any] = {"type": "file_exists", "path": "C:\\scope\\schema.sql"}


def task_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "t-1",
        "project_id": "p-1",
        "parent_id": None,
        "title": "Provision the database",
        "description": "create the schema",
        "origin": "mediator",
        "kind": "setup",
        "state": "pending",
        "state_reason": None,
        "depends_on": [],
        "assigned_role": "engine",
        "position": 0,
    }
    base.update(overrides)

    return base


def criterion_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "c-1",
        "task_id": "t-1",
        "statement": "the schema file exists",
        "check_kind": "deterministic",
        "check_spec": SPEC,
        "weight": 1,
        "status": "unverified",
        "status_reason": None,
        "verified_by": None,
    }
    base.update(overrides)

    return base


def progress_body(task_id: str, percentage: float) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "percentage": percentage,
        "verified_weight": 1.0,
        "counted_weight": 2.0,
        "criteria_total": 2,
        "criteria_verified": 1,
        "criteria_failed": 0,
        "criteria_ignored": 0,
    }


class Recorder:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        return self._responses.pop(0) if self._responses else httpx.Response(200, json={})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def sent(self) -> dict[str, Any]:
        parsed: Any = json.loads(self.last.content.decode("utf-8"))

        assert isinstance(parsed, dict)

        return parsed


def client_for(recorder: Recorder) -> ProjectClient:
    return ProjectClient(BASE_URL, 5.0, transport=recorder.transport())


def ok(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_a_task_is_read_into_its_fields() -> None:
    task = to_task(task_body(depends_on=["t-0"], state_reason="waiting"))

    assert task.id == "t-1"
    assert task.depends_on == ("t-0",)
    assert task.state_reason == "waiting"
    assert task.position == 0


def test_missing_fields_become_empty_rather_than_raising() -> None:
    task = to_task({})

    assert task.id == ""
    assert task.parent_id is None
    assert task.depends_on == ()
    assert task.position == 0


def test_a_blank_reason_reads_as_absent() -> None:
    assert to_task(task_body(state_reason="   ")).state_reason is None


def test_a_settled_task_is_recognised() -> None:
    for state in ("done", "failed", "skipped", "ignored"):
        assert to_task(task_body(state=state)).settled


def test_a_task_still_to_run_is_not_settled() -> None:
    for state in ("pending", "ready", "blocked"):
        task = to_task(task_body(state=state))

        assert not task.settled
        assert task.runnable


def test_a_task_already_moving_is_neither_settled_nor_runnable() -> None:
    task = to_task(task_body(state="in_progress"))

    assert not task.settled
    assert not task.runnable


def test_a_criterion_carries_the_spec_a_check_would_need() -> None:
    criterion = to_criterion(criterion_body())

    assert criterion.check_spec == SPEC
    assert criterion.mechanisable


def test_an_inspected_criterion_is_not_mechanisable() -> None:
    criterion = to_criterion(criterion_body(check_kind="inspected", check_spec=None))

    assert criterion.check_spec is None
    assert not criterion.mechanisable


def test_a_deterministic_criterion_without_a_spec_is_not_mechanisable() -> None:
    assert not to_criterion(criterion_body(check_spec=None)).mechanisable


def test_a_spec_that_is_not_an_object_is_discarded() -> None:
    assert to_criterion(criterion_body(check_spec=["file_exists"])).check_spec is None


def test_a_percentage_arriving_as_a_whole_number_is_read_as_a_float() -> None:
    assert to_progress(progress_body("t-1", 50)).percentage == pytest.approx(50.0)


def test_a_boolean_is_never_read_as_a_number() -> None:
    progress = to_progress({"task_id": "t-1", "percentage": True, "criteria_total": True})

    assert progress.percentage == 0.0
    assert progress.criteria_total == 0


def test_a_snapshot_indexes_its_tasks_by_id() -> None:
    snapshot = to_snapshot(
        {
            "project_id": "p-1",
            "overall": progress_body("__overall__", 25.0),
            "per_task": [progress_body("t-1", 50.0), progress_body("t-2", 0.0)],
        }
    )

    assert snapshot.overall.percentage == pytest.approx(25.0)
    assert snapshot.of("t-1").percentage == pytest.approx(50.0)


def test_a_task_with_no_progress_row_reads_as_zero_rather_than_raising() -> None:
    snapshot = to_snapshot({"overall": progress_body("__overall__", 0.0), "per_task": []})
    reading = snapshot.of("t-9")

    assert reading.task_id == "t-9"
    assert reading.percentage == 0.0
    assert reading.criteria_total == 0


def test_a_snapshot_missing_its_overall_reading_still_parses() -> None:
    assert to_snapshot({}).overall.percentage == 0.0


async def test_tasks_are_fetched_from_the_project() -> None:
    recorder = Recorder([ok([task_body(), task_body(id="t-2", position=1)])])
    fetched = await client_for(recorder).tasks("p-1")

    assert recorder.last.url.path == "/projects/p-1/tasks"
    assert [task.id for task in fetched] == ["t-1", "t-2"]


async def test_entries_that_are_not_objects_are_skipped() -> None:
    recorder = Recorder([ok([task_body(), "nonsense", 7])])

    assert len(await client_for(recorder).tasks("p-1")) == 1


async def test_criteria_are_fetched_for_one_task() -> None:
    recorder = Recorder([ok([criterion_body()])])
    fetched = await client_for(recorder).criteria("t-1")

    assert recorder.last.url.path == "/tasks/t-1/criteria"
    assert fetched[0].check_spec == SPEC


async def test_progress_is_read_and_never_computed() -> None:
    recorder = Recorder(
        [
            ok(
                {
                    "project_id": "p-1",
                    "overall": progress_body("__overall__", 40.0),
                    "per_task": [progress_body("t-1", 80.0)],
                }
            )
        ]
    )
    snapshot: Snapshot = await client_for(recorder).progress("p-1")

    assert recorder.last.url.path == "/projects/p-1/progress"
    assert snapshot.of("t-1").percentage == pytest.approx(80.0)


async def test_moving_a_task_names_the_mediator_as_the_actor() -> None:
    recorder = Recorder([ok(task_body(state="in_progress"))])
    moved = await client_for(recorder).move_task("t-1", "in_progress", None)

    assert recorder.last.url.path == "/tasks/t-1/state"
    assert recorder.sent() == {"state": "in_progress", "reason": None, "actor": ACTOR}
    assert moved.state == "in_progress"


async def test_a_reason_reaches_the_service_when_one_is_required() -> None:
    recorder = Recorder([ok(task_body(state="skipped", state_reason="no database here"))])
    await client_for(recorder).move_task("t-1", "skipped", "no database here")

    assert recorder.sent()["reason"] == "no database here"


async def test_settling_a_criterion_names_the_mediator_as_the_actor() -> None:
    recorder = Recorder([ok(criterion_body(status="verified"))])
    settled = await client_for(recorder).settle_criterion("c-1", "verified", "file found")

    assert recorder.last.url.path == "/criteria/c-1/status"
    assert recorder.sent() == {"status": "verified", "reason": "file found", "actor": ACTOR}
    assert settled.status == "verified"


async def test_moving_a_step_returns_the_state_it_landed_in() -> None:
    recorder = Recorder([ok({"id": "s-1", "state": "running"})])
    state = await client_for(recorder).move_step("s-1", "running", None)

    assert recorder.last.url.path == "/steps/s-1/transitions"
    assert state == "running"


async def test_a_reconciliation_record_carries_every_outcome() -> None:
    recorder = Recorder([ok({"id": "r-1"})])
    outcomes = (
        Outcome("s-1", "succeeded", ("C:\\scope\\schema.sql",), 0, None, None, None),
        Outcome("s-2", "never_attempted", (), None, None, None, None),
    )

    record_id = await client_for(recorder).write_record("t-1", "req-1", "user_stop", outcomes)
    sent = recorder.sent()

    assert recorder.last.url.path == "/tasks/t-1/reconciliations"
    assert record_id == "r-1"
    assert sent["halt_reason"] == "user_stop"
    assert [entry["step_id"] for entry in sent["step_outcomes"]] == ["s-1", "s-2"]


async def test_an_outcome_reports_paths_as_a_list_on_the_wire() -> None:
    recorder = Recorder([ok({"id": "r-1"})])
    outcome = Outcome("s-1", "aborted", ("a", "b"), None, "stopped", None, None)

    await client_for(recorder).write_record("t-1", "req-1", "kill_switch", (outcome,))

    assert recorder.sent()["step_outcomes"][0]["touched_paths"] == ["a", "b"]


async def test_a_refusal_names_the_path_that_was_refused() -> None:
    recorder = Recorder([httpx.Response(409, json={"detail": "illegal transition"})])

    with pytest.raises(ProjectServiceError) as raised:
        await client_for(recorder).move_task("t-1", "done", None)

    assert raised.value.status == 409
    assert "/tasks/t-1/state" in raised.value.detail


async def test_a_non_object_body_is_refused_rather_than_read() -> None:
    recorder = Recorder([ok(["not", "an", "object"])])

    with pytest.raises(ProjectServiceError):
        await client_for(recorder).move_task("t-1", "ready", None)


async def test_a_non_array_body_is_refused_rather_than_read() -> None:
    recorder = Recorder([ok({"tasks": []})])

    with pytest.raises(ProjectServiceError):
        await client_for(recorder).tasks("p-1")


async def test_an_unreachable_service_is_distinguished_from_a_refusal() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = ProjectClient(BASE_URL, 5.0, transport=httpx.MockTransport(unreachable))

    with pytest.raises(ProjectServiceUnreachableError):
        await client.tasks("p-1")

    await client.close()


def stored_step_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "s-1",
        "plan_id": "pl-1",
        "position": 0,
        "description": "apply the schema",
        "service": "task-runner",
        "action": {"type": "run_python_script", "script_path": "apply.py", "arguments": []},
        "requires_confirmation": True,
        "confirmation_reason": "it writes to the database",
        "on_failure": "abort",
        "reversible": False,
        "criterion_refs": ["c-1"],
        "effects": {"writes_paths": ["schema.sql"], "deletes_paths": [], "network": False},
        "state": "awaiting_confirmation",
    }
    base.update(overrides)

    return base


def stored_plan_body(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "pl-1",
        "project_id": "p-1",
        "task_id": "t-1",
        "request_id": "r-1",
        "scope_root": "C:\\scope",
        "intent": "create the schema",
        "rationale": "the task asks for it",
        "steps": list(steps),
        "gated_count": 1,
        "steps_total": len(steps),
        "model_id": "qwen2.5-coder:7b",
        "prompt_name": "router",
        "prompt_version": "v4",
        "prompt_hash": "d9223d1149c4",
    }


async def test_a_stored_step_is_read_from_its_own_route() -> None:
    recorder = Recorder([ok(stored_step_body())])

    await client_for(recorder).stored_step("s-1")

    assert recorder.last.method == "GET"
    assert recorder.last.url.path == "/steps/s-1"


async def test_reading_a_stored_step_sends_no_body() -> None:
    recorder = Recorder([ok(stored_step_body())])

    await client_for(recorder).stored_step("s-1")

    assert recorder.last.content == b""


async def test_a_stored_step_is_handed_back_exactly_as_stored() -> None:
    body = stored_step_body()
    recorder = Recorder([ok(body)])

    assert await client_for(recorder).stored_step("s-1") == body


async def test_a_stored_plan_is_read_from_its_own_route() -> None:
    recorder = Recorder([ok(stored_plan_body())])

    await client_for(recorder).stored_plan("pl-1")

    assert recorder.last.method == "GET"
    assert recorder.last.url.path == "/plans/pl-1"


async def test_a_stored_plan_is_handed_back_with_its_steps_untouched() -> None:
    body = stored_plan_body(stored_step_body(), stored_step_body(id="s-2", position=1))
    recorder = Recorder([ok(body)])

    assert await client_for(recorder).stored_plan("pl-1") == body


async def test_a_missing_step_is_refused_with_the_route_that_failed() -> None:
    recorder = Recorder([httpx.Response(404, json={"detail": "no such step"})])

    with pytest.raises(ProjectServiceError) as raised:
        await client_for(recorder).stored_step("s-9")

    assert raised.value.status == 404
    assert "/steps/s-9" in raised.value.detail


async def test_a_missing_plan_is_refused_with_the_route_that_failed() -> None:
    recorder = Recorder([httpx.Response(404, json={"detail": "no such plan"})])

    with pytest.raises(ProjectServiceError) as raised:
        await client_for(recorder).stored_plan("pl-9")

    assert raised.value.status == 404
    assert "/plans/pl-9" in raised.value.detail


async def test_a_plan_that_comes_back_as_a_list_is_refused() -> None:
    recorder = Recorder([ok([stored_plan_body()])])

    with pytest.raises(ProjectServiceError):
        await client_for(recorder).stored_plan("pl-1")
