from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from mediator_service.dispatch import (
    Event,
    FileWrite,
    Output,
    Plan,
    Result,
    RouterClient,
    RouterError,
    RunnerClient,
    RunnerUnreachableError,
    Step,
    to_plan,
)
from mediator_service.events import TERMINAL_EVENTS, Emitter
from mediator_service.execution import (
    AWAITING,
    COMPLETED,
    FAILED,
    HALTED,
    NO_RESULT,
    Clients,
    TaskPass,
)
from mediator_service.persist import ProjectServiceError, ProjectServiceUnreachableError
from mediator_service.upstream import Criterion, Progress, ProjectClient, Snapshot, Task

PROJECT_ID = "p-1"
TASK_ID = "t-1"
REQUEST_ID = "r-1"
SCOPE_ROOT = "C:\\scope"

DIGEST = "a" * 64


def refuse(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no HTTP call was expected, but one reached {request.url}")


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(refuse)


def task(state: str = "ready", task_id: str = TASK_ID) -> Task:
    return Task(
        id=task_id,
        parent_id=None,
        title="create the schema",
        description="write and apply the schema file",
        kind="code",
        state=state,
        state_reason=None,
        depends_on=(),
        assigned_role="engine",
        position=0,
    )


def criterion(
    criterion_id: str = "c-1",
    check_spec: dict[str, Any] | None = None,
    statement: str = "the schema file exists",
) -> Criterion:
    return Criterion(
        id=criterion_id,
        task_id=TASK_ID,
        statement=statement,
        check_kind="deterministic",
        check_spec=check_spec or {"type": "file_exists", "path": "schema.sql"},
        weight=1,
        status="unverified",
    )


def snapshot(task_percentage: float = 100.0, project_percentage: float = 50.0) -> Snapshot:
    return Snapshot(
        overall=Progress(
            task_id="__overall__",
            percentage=project_percentage,
            criteria_total=2,
            criteria_verified=1,
            criteria_failed=0,
            criteria_ignored=0,
        ),
        per_task={
            TASK_ID: Progress(
                task_id=TASK_ID,
                percentage=task_percentage,
                criteria_total=1,
                criteria_verified=1,
                criteria_failed=0,
                criteria_ignored=0,
            )
        },
    )


def step_body(
    step_id: str = "s-1",
    position: int = 0,
    requires_confirmation: bool = False,
    confirmation_reason: str | None = None,
    on_failure: str = "abort",
    service: str = "task-runner",
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "position": position,
        "description": f"step {step_id}",
        "service": service,
        "action": {"type": "run_python_script", "script_path": "build.py", "arguments": []},
        "requires_confirmation": requires_confirmation,
        "confirmation_reason": confirmation_reason,
        "on_failure": on_failure,
        "reversible": True,
        "criterion_refs": ["c-1"],
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


def plan_of(*steps: dict[str, Any]) -> Plan:
    return to_plan(
        {
            "plan_id": "pl-1",
            "project_id": PROJECT_ID,
            "task_id": TASK_ID,
            "request_id": REQUEST_ID,
            "scope_root": SCOPE_ROOT,
            "intent": "create the schema",
            "rationale": "the task asks for it",
            "steps": list(steps),
            "gated_count": sum(1 for entry in steps if entry["requires_confirmation"]),
            "model_id": "qwen2.5-coder:7b",
            "prompt_name": "router",
            "prompt_version": "v4",
            "prompt_hash": "d9223d1149c4",
        }
    )


def succeeded(step_id: str = "s-1", files: tuple[FileWrite, ...] = ()) -> Result:
    return Result(
        step_id=step_id,
        state="succeeded",
        exit_code=0,
        terminated_by=None,
        error_message=None,
        files_written=files,
        files_deleted=(),
        ports_opened=(),
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
    )


def failed(step_id: str = "s-1", exit_code: int = 1, message: str | None = None) -> Result:
    return Result(
        step_id=step_id,
        state="failed",
        exit_code=exit_code,
        terminated_by=None,
        error_message=message,
        files_written=(),
        files_deleted=(),
        ports_opened=(),
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
    )


def spoke(step_id: str = "s-1", sequence: int = 0, message: str = "working\n") -> Output:
    return Output(step_id=step_id, stream="stdout", sequence=sequence, text=message)


class Halt:
    def __init__(self, after: int | None) -> None:
        self._after = after
        self._checks = 0

    def __call__(self) -> bool:
        if self._after is None:
            return False

        reached = self._checks >= self._after
        self._checks += 1

        return reached


class FakeRouter(RouterClient):
    def __init__(self, plan: Plan | None = None, failure: Exception | None = None) -> None:
        super().__init__("http://router.test", 5.0, 1.0, transport=transport())
        self._plan = plan
        self._failure = failure
        self.calls: list[tuple[str, str, str]] = []

    async def plan(self, project_id: str, task_id: str, request_id: str) -> Plan:
        self.calls.append((project_id, task_id, request_id))

        if self._failure is not None:
            raise self._failure

        assert self._plan is not None

        return self._plan


class FakeRunner(RunnerClient):
    def __init__(
        self,
        scripts: dict[str, list[Event]] | None = None,
        failure: Exception | None = None,
    ) -> None:
        super().__init__("http://runner.test", 5.0, 1.0, transport=transport())
        self._scripts = scripts or {}
        self._failure = failure
        self.dispatched: list[tuple[str, str, str, bool]] = []

    async def dispatch(
        self, step: Step, scope_root: str, task_id: str, confirmed: bool
    ) -> AsyncIterator[Event]:
        self.dispatched.append((step.step_id, scope_root, task_id, confirmed))

        if self._failure is not None:
            raise self._failure

        for event in self._scripts.get(step.step_id, []):
            yield event


class FakeProject(ProjectClient):
    def __init__(
        self,
        criteria: tuple[Criterion, ...] = (),
        progress: Snapshot | None = None,
        failures: dict[str, Exception] | None = None,
    ) -> None:
        super().__init__("http://project.test", 5.0, transport=transport())
        self._criteria = criteria
        self._progress = progress if progress is not None else snapshot()
        self._failures = failures or {}
        self.task_moves: list[tuple[str, str, str | None]] = []
        self.step_moves: list[tuple[str, str, str | None]] = []
        self.settled: list[tuple[str, str, str | None]] = []

    def _guard(self, name: str) -> None:
        failure = self._failures.get(name)

        if failure is not None:
            raise failure

    async def criteria(self, task_id: str) -> tuple[Criterion, ...]:
        self._guard("criteria")

        return self._criteria

    async def progress(self, project_id: str) -> Snapshot:
        self._guard("progress")

        return self._progress

    async def move_task(self, task_id: str, state: str, reason: str | None) -> Task:
        self._guard("move_task")
        self.task_moves.append((task_id, state, reason))

        return task(state=state, task_id=task_id)

    async def move_step(self, step_id: str, state: str, reason: str | None) -> str:
        self._guard("move_step")
        self.step_moves.append((step_id, state, reason))

        return state

    async def settle_criterion(
        self, criterion_id: str, status: str, reason: str | None
    ) -> Criterion:
        self._guard("settle_criterion")
        self.settled.append((criterion_id, status, reason))

        return criterion(criterion_id=criterion_id)


@dataclass
class Ran:
    run: TaskPass
    router: FakeRouter
    runner: FakeRunner
    project: FakeProject
    emitted: list[dict[str, Any]] = field(default_factory=list)

    def names(self) -> list[str]:
        return [entry["event"] for entry in self.emitted]

    def only(self, name: str) -> list[dict[str, Any]]:
        return [entry for entry in self.emitted if entry["event"] == name]

    def one(self, name: str) -> dict[str, Any]:
        found = self.only(name)

        assert len(found) == 1

        return found[0]

    def task_states(self) -> list[str]:
        return [state for _, state, _ in self.project.task_moves]

    def step_states(self) -> list[tuple[str, str]]:
        return [(step_id, state) for step_id, state, _ in self.project.step_moves]


async def run_pass(
    *,
    steps: tuple[dict[str, Any], ...] = (),
    scripts: dict[str, list[Event]] | None = None,
    task_state: str = "ready",
    criteria: tuple[Criterion, ...] = (),
    progress: Snapshot | None = None,
    router_failure: Exception | None = None,
    runner_failure: Exception | None = None,
    project_failures: dict[str, Exception] | None = None,
    halt_after: int | None = None,
) -> Ran:
    router = FakeRouter(plan_of(*steps), router_failure)
    runner = FakeRunner(scripts, runner_failure)
    project = FakeProject(criteria, progress, project_failures)

    walker = TaskPass(
        Clients(router, runner, project),
        Emitter(REQUEST_ID, PROJECT_ID),
        PROJECT_ID,
        REQUEST_ID,
        task(state=task_state),
        0,
        1,
        Halt(halt_after),
    )

    ran = Ran(walker, router, runner, project)

    async for chunk in walker.stream():
        ran.emitted.append(json.loads(chunk.decode("utf-8")))

    await router.close()
    await runner.close()
    await project.close()

    return ran


async def test_a_pending_task_is_made_ready_before_it_is_started() -> None:
    ran = await run_pass(task_state="pending", steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.task_states()[:2] == ["ready", "in_progress"]


async def test_a_ready_task_goes_straight_to_in_progress() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.task_states()[0] == "in_progress"


async def test_the_plan_is_asked_for_with_the_runs_correlation_id() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.router.calls == [(PROJECT_ID, TASK_ID, REQUEST_ID)]


async def test_the_plan_totals_are_announced_before_any_step_runs() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.names().index("plan_ready") < ran.names().index("step_started")
    assert ran.one("plan_ready")["steps_total"] == 1


async def test_steps_run_in_position_order_not_the_order_the_router_listed_them() -> None:
    ran = await run_pass(
        steps=(step_body("s-2", position=1), step_body("s-1", position=0)),
        scripts={"s-1": [succeeded("s-1")], "s-2": [succeeded("s-2")]},
    )

    assert [entry[0] for entry in ran.runner.dispatched] == ["s-1", "s-2"]


async def test_a_completed_task_is_verified_before_it_is_marked_done() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.task_states()[-2:] == ["verifying", "done"]
    assert ran.run.state == COMPLETED


async def test_the_finish_carries_the_percentages_project_service_reported() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})
    finished = ran.one("task_finished")

    assert finished["task_percentage"] == 100.0
    assert finished["project_percentage"] == 50.0


async def test_a_step_is_running_before_it_is_dispatched_and_settled_after() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.step_states() == [("s-1", "running"), ("s-1", "succeeded")]


async def test_output_reaches_the_stream_as_step_output() -> None:
    ran = await run_pass(
        steps=(step_body(),), scripts={"s-1": [spoke(message="hello\n"), succeeded()]}
    )

    assert ran.one("step_output")["text"] == "hello\n"


async def test_a_step_is_always_dispatched_unconfirmed() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.runner.dispatched == [("s-1", SCOPE_ROOT, TASK_ID, False)]


async def test_a_failing_step_is_settled_with_a_reason_built_from_its_exit_code() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [failed(exit_code=2)]})
    reasons = [reason for _, state, reason in ran.project.step_moves if state == "failed"]

    assert reasons == ["the step exited with code 2"]


async def test_a_failing_step_prefers_the_message_the_runner_gave() -> None:
    ran = await run_pass(
        steps=(step_body(),), scripts={"s-1": [failed(message="the venv is missing")]}
    )
    reasons = [reason for _, state, reason in ran.project.step_moves if state == "failed"]

    assert reasons == ["the venv is missing"]


async def test_a_failure_stops_the_steps_that_would_have_followed() -> None:
    ran = await run_pass(
        steps=(step_body("s-1", position=0), step_body("s-2", position=1)),
        scripts={"s-1": [failed("s-1")], "s-2": [succeeded("s-2")]},
    )

    assert [entry[0] for entry in ran.runner.dispatched] == ["s-1"]
    assert ran.run.state == FAILED


async def test_a_failure_marked_continue_lets_the_next_step_run() -> None:
    ran = await run_pass(
        steps=(step_body("s-1", position=0, on_failure="continue"), step_body("s-2", position=1)),
        scripts={"s-1": [failed("s-1")], "s-2": [succeeded("s-2")]},
    )

    assert [entry[0] for entry in ran.runner.dispatched] == ["s-1", "s-2"]
    assert ran.run.state == COMPLETED


async def test_a_failed_task_is_moved_to_failed_with_its_reason() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [failed(message="it broke")]})
    moves = [(state, reason) for _, state, reason in ran.project.task_moves]

    assert moves[-1] == ("failed", "it broke")


async def test_a_runner_that_closes_without_a_result_is_a_failure() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": []})

    assert ran.run.state == FAILED
    assert ran.run.reason == NO_RESULT


async def test_a_gated_step_is_never_dispatched() -> None:
    ran = await run_pass(
        steps=(step_body(requires_confirmation=True, confirmation_reason="it deletes files"),),
        scripts={"s-1": [succeeded()]},
    )

    assert ran.runner.dispatched == []
    assert ran.run.state == AWAITING


async def test_a_gated_step_parks_both_the_step_and_the_task() -> None:
    ran = await run_pass(
        steps=(step_body(requires_confirmation=True, confirmation_reason="it deletes files"),)
    )

    assert ran.step_states() == [("s-1", "awaiting_confirmation")]
    assert ran.task_states()[-1] == "awaiting_confirmation"


async def test_the_confirmation_reason_reaches_the_stream() -> None:
    ran = await run_pass(
        steps=(step_body(requires_confirmation=True, confirmation_reason="it deletes files"),)
    )

    assert ran.one("step_awaiting_confirmation")["reason"] == "it deletes files"
    assert ran.run.awaiting_step_id == "s-1"


async def test_a_gate_stops_the_steps_behind_it() -> None:
    ran = await run_pass(
        steps=(step_body("s-1", position=0, requires_confirmation=True), step_body("s-2", 1)),
        scripts={"s-2": [succeeded("s-2")]},
    )

    assert ran.runner.dispatched == []


async def test_a_halt_stops_the_pass_before_the_first_step() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]}, halt_after=0)

    assert ran.runner.dispatched == []
    assert ran.run.state == HALTED


async def test_a_halt_leaves_the_task_where_it_found_it() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]}, halt_after=0)

    assert ran.task_states() == ["in_progress"]


async def test_a_halt_between_steps_lets_the_first_one_finish() -> None:
    ran = await run_pass(
        steps=(step_body("s-1", position=0), step_body("s-2", position=1)),
        scripts={"s-1": [succeeded("s-1")], "s-2": [succeeded("s-2")]},
        halt_after=1,
    )

    assert [entry[0] for entry in ran.runner.dispatched] == ["s-1"]
    assert ran.run.state == HALTED


async def test_a_criterion_the_run_proved_is_settled() -> None:
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [succeeded(files=(FileWrite("C:\\scope\\schema.sql", DIGEST, 12),))]},
        criteria=(criterion(),),
    )

    assert ran.project.settled[0][0] == "c-1"
    assert ran.project.settled[0][1] == "verified"


async def test_a_criterion_with_no_evidence_is_never_written() -> None:
    ran = await run_pass(
        steps=(step_body(),), scripts={"s-1": [succeeded()]}, criteria=(criterion(),)
    )

    assert ran.project.settled == []
    assert ran.only("criterion_settled") == []


async def test_a_settled_criterion_reaches_the_stream_with_its_statement() -> None:
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [succeeded(files=(FileWrite("C:\\scope\\schema.sql", DIGEST, 12),))]},
        criteria=(criterion(statement="the schema file exists"),),
    )

    assert ran.one("criterion_settled")["statement"] == "the schema file exists"


async def test_criteria_are_still_settled_after_a_step_fails() -> None:
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [failed()]},
        criteria=(criterion(),),
    )

    assert "criterion_settled" not in ran.names()
    assert ran.run.state == FAILED


async def test_a_router_failure_fails_the_task_without_ending_the_run() -> None:
    ran = await run_pass(router_failure=RouterError(502, "the plan was rejected"))

    assert ran.run.state == FAILED
    assert "the plan was rejected" in str(ran.run.reason)
    assert not set(ran.names()) & TERMINAL_EVENTS


async def test_a_runner_failure_fails_the_task() -> None:
    ran = await run_pass(
        steps=(step_body(),), runner_failure=RunnerUnreachableError("http://runner.test")
    )

    assert ran.run.state == FAILED
    assert "unreachable" in str(ran.run.reason)


async def test_a_refusal_while_concluding_still_reports_the_task() -> None:
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [succeeded()]},
        project_failures={"move_task": ProjectServiceError(409, "an illegal transition")},
    )

    assert ran.names()[-1] == "task_finished"
    assert ran.run.state == FAILED


async def test_percentages_fall_back_to_zero_when_progress_cannot_be_read() -> None:
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [succeeded()]},
        project_failures={"progress": ProjectServiceUnreachableError("http://project.test")},
    )
    finished = ran.one("task_finished")

    assert finished["task_percentage"] == 0.0
    assert finished["project_percentage"] == 0.0


async def test_the_pass_opens_with_task_started_and_closes_with_task_finished() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [succeeded()]})

    assert ran.names()[0] == "task_started"
    assert ran.names()[-1] == "task_finished"


async def test_every_event_is_stamped_in_sequence() -> None:
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [spoke(), succeeded()]})

    assert [entry["sequence"] for entry in ran.emitted] == list(range(len(ran.emitted)))
    assert {entry["request_id"] for entry in ran.emitted} == {REQUEST_ID}


async def test_an_outcome_is_recorded_against_the_step_the_loop_dispatched() -> None:
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [succeeded(step_id="wrong-id")]},
    )

    assert [outcome.step_id for outcome in ran.run.outcomes] == ["s-1"]


async def test_a_step_routed_elsewhere_fails_the_task_rather_than_being_skipped() -> None:
    ran = await run_pass(
        steps=(step_body(service="automation"),),
        scripts={"s-1": [succeeded()]},
    )

    assert ran.run.state == FAILED


@pytest.mark.parametrize("state", ["succeeded", "failed"])
async def test_a_step_is_settled_in_the_state_the_runner_reported(state: str) -> None:
    result = succeeded() if state == "succeeded" else failed()
    ran = await run_pass(steps=(step_body(),), scripts={"s-1": [result]})

    assert ran.step_states()[-1] == ("s-1", state)
