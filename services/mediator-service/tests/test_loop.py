from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from bison_contracts.halt import HaltReason, HaltSignal, HaltState

from mediator_service.dispatch import (
    Event,
    Plan,
    Result,
    RouterClient,
    RunnerClient,
    Step,
    to_plan,
)
from mediator_service.execution import Clients
from mediator_service.loop import NO_TASKS, RunLoop
from mediator_service.persist import ProjectServiceUnreachableError
from mediator_service.upstream import Criterion, Outcome, Progress, ProjectClient, Snapshot, Task

PROJECT_ID = "p-1"
REQUEST_ID = "r-1"
SCOPE_ROOT = "C:\\scope"


def refuse(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no HTTP call was expected, but one reached {request.url}")


def transport() -> httpx.MockTransport:
    return httpx.MockTransport(refuse)


def task(
    task_id: str,
    position: int = 0,
    state: str = "ready",
    depends_on: tuple[str, ...] = (),
) -> Task:
    return Task(
        id=task_id,
        parent_id=None,
        title=f"task {task_id}",
        description="do the thing",
        kind="code",
        state=state,
        state_reason=None,
        depends_on=depends_on,
        assigned_role="engine",
        position=position,
    )


def step_body(step_id: str) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "position": 0,
        "description": f"step {step_id}",
        "service": "task-runner",
        "action": {"type": "run_python_script", "script_path": "build.py", "arguments": []},
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


def gated_body(step_id: str) -> dict[str, Any]:
    body = step_body(step_id)
    body["requires_confirmation"] = True
    body["confirmation_reason"] = "it deletes files"

    return body


def plan_for(task_id: str, *steps: dict[str, Any]) -> Plan:
    return to_plan(
        {
            "plan_id": f"pl-{task_id}",
            "project_id": PROJECT_ID,
            "task_id": task_id,
            "request_id": REQUEST_ID,
            "scope_root": SCOPE_ROOT,
            "intent": "do the thing",
            "rationale": "the task asks for it",
            "steps": [{**entry, "position": index} for index, entry in enumerate(steps)],
            "gated_count": sum(1 for entry in steps if entry["requires_confirmation"]),
            "model_id": "qwen2.5-coder:7b",
            "prompt_name": "router",
            "prompt_version": "v4",
            "prompt_hash": "d9223d1149c4",
        }
    )


def succeeded(step_id: str) -> Result:
    return Result(
        step_id=step_id,
        state="succeeded",
        exit_code=0,
        terminated_by=None,
        error_message=None,
        files_written=(),
        files_deleted=(),
        ports_opened=(),
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
    )


def failed(step_id: str) -> Result:
    return Result(
        step_id=step_id,
        state="failed",
        exit_code=1,
        terminated_by=None,
        error_message="it broke",
        files_written=(),
        files_deleted=(),
        ports_opened=(),
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
    )


def snapshot(percentage: float = 42.0) -> Snapshot:
    return Snapshot(
        overall=Progress(
            task_id="__overall__",
            percentage=percentage,
            criteria_total=0,
            criteria_verified=0,
            criteria_failed=0,
            criteria_ignored=0,
        ),
        per_task={},
    )


class Switch(HaltState):
    def __init__(self) -> None:
        super().__init__("mediator-service", "between_tasks")

    def trip(self, reason: HaltReason = "kill_switch") -> None:
        self.accept(HaltSignal(id="h-1", reason=reason, issued_at=datetime.now(UTC)))


class FakeRouter(RouterClient):
    def __init__(self, plans: dict[str, Plan]) -> None:
        super().__init__("http://router.test", 5.0, 1.0, transport=transport())
        self._plans = plans
        self.asked: list[str] = []

    async def plan(self, project_id: str, task_id: str, request_id: str) -> Plan:
        self.asked.append(task_id)

        return self._plans.get(task_id, plan_for(task_id))


class FakeRunner(RunnerClient):
    def __init__(self, scripts: dict[str, list[Event]]) -> None:
        super().__init__("http://runner.test", 5.0, 1.0, transport=transport())
        self._scripts = scripts
        self.dispatched: list[str] = []

    async def dispatch(
        self, step: Step, scope_root: str, task_id: str, confirmed: bool
    ) -> AsyncIterator[Event]:
        self.dispatched.append(step.step_id)

        for event in self._scripts.get(step.step_id, [succeeded(step.step_id)]):
            yield event


class FakeProject(ProjectClient):
    def __init__(
        self,
        tasks: tuple[Task, ...],
        failure: Exception | None = None,
        on_step: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__("http://project.test", 5.0, transport=transport())
        self._tasks = tasks
        self._failure = failure
        self._on_step = on_step
        self.records: list[tuple[str, str, tuple[Outcome, ...]]] = []
        self.task_moves: list[tuple[str, str]] = []

    async def tasks(self, project_id: str) -> tuple[Task, ...]:
        if self._failure is not None:
            raise self._failure

        return self._tasks

    async def criteria(self, task_id: str) -> tuple[Criterion, ...]:
        return ()

    async def progress(self, project_id: str) -> Snapshot:
        return snapshot()

    async def move_task(self, task_id: str, state: str, reason: str | None) -> Task:
        self.task_moves.append((task_id, state))

        return task(task_id, state=state)

    async def move_step(self, step_id: str, state: str, reason: str | None) -> str:
        if self._on_step is not None:
            self._on_step(step_id, state)

        return state

    async def settle_criterion(
        self, criterion_id: str, status: str, reason: str | None
    ) -> Criterion:
        raise AssertionError("no criterion was expected to settle in these runs")

    async def write_record(
        self,
        task_id: str,
        request_id: str,
        halt_reason: str,
        outcomes: tuple[Outcome, ...],
    ) -> str:
        self.records.append((task_id, halt_reason, outcomes))

        return f"rec-{len(self.records)}"


class Ran:
    def __init__(self, loop: RunLoop, router: FakeRouter, runner: FakeRunner, project: FakeProject):
        self.loop = loop
        self.router = router
        self.runner = runner
        self.project = project
        self.emitted: list[dict[str, Any]] = []

    def names(self) -> list[str]:
        return [entry["event"] for entry in self.emitted]

    def only(self, name: str) -> list[dict[str, Any]]:
        return [entry for entry in self.emitted if entry["event"] == name]

    def one(self, name: str) -> dict[str, Any]:
        found = self.only(name)

        assert len(found) == 1

        return found[0]

    def started(self) -> list[str]:
        return [entry["task_id"] for entry in self.only("task_started")]


async def run_loop(
    tasks: tuple[Task, ...],
    plans: dict[str, Plan] | None = None,
    scripts: dict[str, list[Event]] | None = None,
    halt: Switch | None = None,
    halt_on: tuple[str, str] | None = None,
    failure: Exception | None = None,
) -> Ran:
    switch = halt or Switch()

    def watch(step_id: str, state: str) -> None:
        if halt_on is not None and (step_id, state) == halt_on:
            switch.trip()

    router = FakeRouter(plans or {})
    runner = FakeRunner(scripts or {})
    project = FakeProject(tasks, failure, watch if halt_on else None)

    loop = RunLoop(Clients(router, runner, project), switch, PROJECT_ID, REQUEST_ID)
    ran = Ran(loop, router, runner, project)

    async for chunk in loop.stream():
        ran.emitted.append(json.loads(chunk.decode("utf-8")))

    await router.close()
    await runner.close()
    await project.close()

    return ran


async def test_the_run_opens_by_announcing_the_order() -> None:
    ran = await run_loop((task("t-1", 0), task("t-2", 1, depends_on=("t-1",))))

    assert ran.names()[0] == "run_started"
    assert ran.one("run_started")["order"] == ["t-1", "t-2"]
    assert ran.one("run_started")["tasks_total"] == 2


async def test_a_dependency_runs_before_the_task_that_waits_on_it() -> None:
    ran = await run_loop((task("t-2", 0, depends_on=("t-1",)), task("t-1", 1)))

    assert ran.started() == ["t-1", "t-2"]


async def test_a_finished_run_reports_what_it_completed() -> None:
    ran = await run_loop((task("t-1", 0), task("t-2", 1)))
    finished = ran.one("run_finished")

    assert finished["tasks_completed"] == 2
    assert finished["tasks_failed"] == 0
    assert finished["tasks_total"] == 2


async def test_the_run_finish_carries_the_overall_percentage() -> None:
    ran = await run_loop((task("t-1"),))

    assert ran.one("run_finished")["project_percentage"] == 42.0


async def test_a_failed_task_does_not_stop_an_independent_one() -> None:
    ran = await run_loop(
        (task("t-1", 0), task("t-2", 1)),
        plans={"t-1": plan_for("t-1", step_body("s-1")), "t-2": plan_for("t-2", step_body("s-2"))},
        scripts={"s-1": [failed("s-1")]},
    )
    finished = ran.one("run_finished")

    assert ran.started() == ["t-1", "t-2"]
    assert (finished["tasks_completed"], finished["tasks_failed"]) == (1, 1)


async def test_a_task_whose_dependency_failed_is_never_started() -> None:
    ran = await run_loop(
        (task("t-1", 0), task("t-2", 1, depends_on=("t-1",))),
        plans={"t-1": plan_for("t-1", step_body("s-1"))},
        scripts={"s-1": [failed("s-1")]},
    )

    assert ran.started() == ["t-1"]
    assert ran.one("run_finished")["tasks_failed"] == 1


async def test_a_task_already_done_is_not_run_again_but_still_unblocks_its_dependent() -> None:
    ran = await run_loop((task("t-1", 0, state="done"), task("t-2", 1, depends_on=("t-1",))))

    assert ran.started() == ["t-2"]
    assert ran.one("run_finished")["tasks_completed"] == 1


async def test_a_task_already_failed_is_not_retried() -> None:
    ran = await run_loop((task("t-1", 0, state="failed"), task("t-2", 1)))

    assert ran.started() == ["t-2"]


async def test_a_skipped_dependency_leaves_its_dependent_unrun() -> None:
    ran = await run_loop((task("t-1", 0, state="skipped"), task("t-2", 1, depends_on=("t-1",))))

    assert ran.started() == []
    assert ran.one("run_finished")["tasks_completed"] == 0


async def test_a_gated_task_parks_the_run_and_the_rest_is_left_alone() -> None:
    ran = await run_loop(
        (task("t-1", 0), task("t-2", 1)),
        plans={"t-1": plan_for("t-1", gated_body("s-1"))},
    )

    assert ran.started() == ["t-1"]
    assert ran.loop.awaiting_task_id == "t-1"
    assert ran.runner.dispatched == []


async def test_a_halt_before_the_first_task_dispatches_nothing() -> None:
    switch = Switch()
    switch.trip()

    ran = await run_loop((task("t-1"),), halt=switch)

    assert ran.router.asked == []
    assert ran.names() == ["run_started", "halted"]


async def test_a_halt_before_the_first_task_writes_no_record() -> None:
    switch = Switch()
    switch.trip()

    ran = await run_loop((task("t-1"),), halt=switch)

    assert ran.project.records == []
    assert ran.one("halted")["record_id"] is None


async def test_a_halt_inside_a_task_records_what_had_already_run() -> None:
    ran = await run_loop(
        (task("t-1"),),
        plans={"t-1": plan_for("t-1", step_body("s-1"), step_body("s-2"))},
        halt_on=("s-1", "succeeded"),
    )

    assert ran.runner.dispatched == ["s-1"]
    assert len(ran.project.records) == 1

    task_id, reason, outcomes = ran.project.records[0]

    assert task_id == "t-1"
    assert reason == "kill_switch"
    assert [outcome.step_id for outcome in outcomes] == ["s-1"]


async def test_the_halt_event_names_the_task_and_the_record() -> None:
    ran = await run_loop(
        (task("t-1"),),
        plans={"t-1": plan_for("t-1", step_body("s-1"), step_body("s-2"))},
        halt_on=("s-1", "succeeded"),
    )
    stopped = ran.one("halted")

    assert stopped["task_id"] == "t-1"
    assert stopped["record_id"] == "rec-1"
    assert stopped["reason"] == "kill_switch"


async def test_a_halt_ends_the_stream_without_a_run_finished() -> None:
    ran = await run_loop(
        (task("t-1"), task("t-2", 1)),
        plans={"t-1": plan_for("t-1", step_body("s-1"), step_body("s-2"))},
        halt_on=("s-1", "succeeded"),
    )

    assert ran.names()[-1] == "halted"
    assert ran.only("run_finished") == []
    assert ran.started() == ["t-1"]


async def test_a_project_with_no_tasks_says_so() -> None:
    ran = await run_loop(())

    assert ran.names() == ["error"]
    assert ran.one("error")["detail"] == NO_TASKS


async def test_a_dependency_cycle_ends_the_run_before_anything_starts() -> None:
    ran = await run_loop((task("t-1", 0, depends_on=("t-2",)), task("t-2", 1, depends_on=("t-1",))))

    assert ran.names() == ["error"]
    assert "cycle" in ran.one("error")["detail"]


async def test_a_project_service_that_cannot_be_reached_ends_the_run() -> None:
    ran = await run_loop(
        (task("t-1"),), failure=ProjectServiceUnreachableError("http://project.test")
    )

    assert ran.names() == ["error"]
    assert "unreachable" in ran.one("error")["detail"]


async def test_one_sequence_counter_covers_the_whole_run() -> None:
    ran = await run_loop((task("t-1", 0), task("t-2", 1)))

    assert [entry["sequence"] for entry in ran.emitted] == list(range(len(ran.emitted)))
    assert {entry["request_id"] for entry in ran.emitted} == {REQUEST_ID}
    assert {entry["project_id"] for entry in ran.emitted} == {PROJECT_ID}


async def test_each_task_is_told_its_position_in_the_run() -> None:
    ran = await run_loop((task("t-1", 0), task("t-2", 1)))
    positions = [(entry["task_id"], entry["position"]) for entry in ran.only("task_started")]

    assert positions == [("t-1", 0), ("t-2", 1)]
