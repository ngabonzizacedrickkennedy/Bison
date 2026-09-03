from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Final

from mediator_service import events, settle
from mediator_service.dispatch import (
    SUCCEEDED,
    TASK_RUNNER_SERVICE,
    Output,
    Plan,
    Result,
    RouterClient,
    RouterError,
    RouterUnreachableError,
    RunnerClient,
    RunnerError,
    RunnerStreamError,
    RunnerUnreachableError,
    Step,
    UnroutableStepError,
)
from mediator_service.events import Emitter
from mediator_service.persist import ProjectServiceError, ProjectServiceUnreachableError
from mediator_service.resolve import UnrunnableActionError
from mediator_service.upstream import Outcome, ProjectClient, Task

PENDING: Final[str] = "pending"
READY: Final[str] = "ready"
IN_PROGRESS: Final[str] = "in_progress"
AWAITING_CONFIRMATION: Final[str] = "awaiting_confirmation"
VERIFYING: Final[str] = "verifying"
DONE: Final[str] = "done"
TASK_FAILED: Final[str] = "failed"

STEP_RUNNING: Final[str] = "running"
STEP_AWAITING: Final[str] = "awaiting_confirmation"

CONTINUE: Final[str] = "continue"

COMPLETED: Final[str] = "completed"
FAILED: Final[str] = "failed"
AWAITING: Final[str] = "awaiting_confirmation"
HALTED: Final[str] = "halted"

NOT_RUN: Final[str] = "the task pass did not complete"
NO_RESULT: Final[str] = "the runner closed the stream without reporting a result"
HALT_REASON: Final[str] = "the run was halted before this step"
NEEDS_CONFIRMATION: Final[str] = "this step needs confirmation"

UPSTREAM_FAILURES: Final[tuple[type[Exception], ...]] = (
    ProjectServiceError,
    ProjectServiceUnreachableError,
    RouterError,
    RouterUnreachableError,
    RunnerError,
    RunnerStreamError,
    RunnerUnreachableError,
    UnroutableStepError,
    UnrunnableActionError,
)


@dataclass(frozen=True)
class Clients:
    router: RouterClient
    runner: RunnerClient
    project: ProjectClient


def ordered(steps: tuple[Step, ...]) -> tuple[Step, ...]:
    return tuple(sorted(steps, key=lambda step: step.position))


def undispatchable(step: Step) -> str:
    if step.service != TASK_RUNNER_SERVICE:
        return (
            f"step {step.step_id} is routed to {step.service}, "
            "which the mediator cannot dispatch yet"
        )

    return f"step {step.step_id} carries no action the runner can execute"


def step_reason(result: Result) -> str | None:
    if result.state == SUCCEEDED:
        return None

    if result.error_message:
        return result.error_message

    if result.terminated_by:
        return f"the step was terminated by {result.terminated_by}"

    return f"the step exited with code {result.exit_code}"


def outcome_of(step: Step, result: Result) -> Outcome:
    return Outcome(
        step_id=step.step_id,
        state=result.state,
        touched_paths=result.touched_paths,
        exit_code=result.exit_code,
        error_message=result.error_message,
        started_at=result.started_at,
        ended_at=result.ended_at,
    )


class TaskPass:
    def __init__(
        self,
        clients: Clients,
        emitter: Emitter,
        project_id: str,
        request_id: str,
        task: Task,
        position: int,
        tasks_total: int,
        halted: Callable[[], bool],
    ) -> None:
        self._clients = clients
        self._emitter = emitter
        self._project_id = project_id
        self._request_id = request_id
        self._task = task
        self._position = position
        self._tasks_total = tasks_total
        self._halted = halted
        self._results: list[Result] = []
        self._outcomes: list[Outcome] = []
        self.state = FAILED
        self.reason: str | None = NOT_RUN
        self.awaiting_step_id: str | None = None

    @property
    def results(self) -> tuple[Result, ...]:
        return tuple(self._results)

    @property
    def outcomes(self) -> tuple[Outcome, ...]:
        return tuple(self._outcomes)

    async def stream(self) -> AsyncIterator[bytes]:
        yield self._emitter.emit(
            events.task_started(self._task.id, self._task.title, self._position, self._tasks_total)
        )

        try:
            async for chunk in self._walk():
                yield chunk
        except UPSTREAM_FAILURES as failure:
            self.state = FAILED
            self.reason = str(failure)

        try:
            await self._conclude()
        except UPSTREAM_FAILURES as failure:
            self.state = FAILED
            self.reason = str(failure)

        task_percentage, project_percentage = await self._percentages()

        yield self._emitter.emit(
            events.task_finished(
                self._task.id, self.state, self.reason, task_percentage, project_percentage
            )
        )

    async def _walk(self) -> AsyncIterator[bytes]:
        await self._begin()

        plan = await self._clients.router.plan(self._project_id, self._task.id, self._request_id)

        yield self._emitter.emit(
            events.plan_ready(self._task.id, plan.plan_id, plan.steps_total, plan.gated_count)
        )

        failure: str | None = None

        for step in ordered(plan.steps):
            if self._halted():
                self.state = HALTED
                self.reason = HALT_REASON

                return

            if step.requires_confirmation:
                async for chunk in self._gate(step):
                    yield chunk

                return

            if not step.dispatchable:
                failure = undispatchable(step)

                if step.on_failure != CONTINUE:
                    break

                continue

            before = len(self._results)

            async for chunk in self._run(step, plan):
                yield chunk

            failure = self._verdict(before)

            if failure is not None and step.on_failure != CONTINUE:
                break

        async for chunk in self._criteria(plan):
            yield chunk

        self.state = FAILED if failure is not None else COMPLETED
        self.reason = failure

    def _verdict(self, before: int) -> str | None:
        if len(self._results) == before:
            return NO_RESULT

        result = self._results[-1]

        return None if result.ok else step_reason(result)

    async def _begin(self) -> None:
        state = self._task.state

        if state == PENDING:
            await self._clients.project.move_task(self._task.id, READY, None)
            state = READY

        if state != IN_PROGRESS:
            await self._clients.project.move_task(self._task.id, IN_PROGRESS, None)

    async def _gate(self, step: Step) -> AsyncIterator[bytes]:
        await self._clients.project.move_step(step.step_id, STEP_AWAITING, None)

        self.state = AWAITING
        self.reason = step.confirmation_reason or NEEDS_CONFIRMATION
        self.awaiting_step_id = step.step_id

        yield self._emitter.emit(
            events.step_awaiting_confirmation(
                self._task.id,
                step.step_id,
                step.position,
                step.description,
                step.confirmation_reason,
            )
        )

    async def _run(self, step: Step, plan: Plan) -> AsyncIterator[bytes]:
        await self._clients.project.move_step(step.step_id, STEP_RUNNING, None)

        yield self._emitter.emit(
            events.step_started(self._task.id, step.step_id, step.position, step.description)
        )

        stream = self._clients.runner.dispatch(step, plan.scope_root, self._task.id, False)

        async for event in stream:
            if isinstance(event, Output):
                yield self._emitter.emit(
                    events.step_output(
                        self._task.id, step.step_id, event.stream, event.sequence, event.text
                    )
                )

                continue

            self._results.append(event)
            self._outcomes.append(outcome_of(step, event))

            await self._clients.project.move_step(step.step_id, event.state, step_reason(event))

            yield self._emitter.emit(
                events.step_finished(
                    self._task.id,
                    step.step_id,
                    event.state,
                    event.exit_code,
                    event.terminated_by,
                    event.error_message,
                )
            )

    async def _criteria(self, plan: Plan) -> AsyncIterator[bytes]:
        criteria = await self._clients.project.criteria(self._task.id)
        statements = {criterion.id: criterion.statement for criterion in criteria}

        for entry in settle.verdicts(criteria, self.results, plan.scope_root):
            if entry.status is None:
                continue

            await self._clients.project.settle_criterion(
                entry.criterion_id, entry.status, entry.detail
            )

            yield self._emitter.emit(
                events.criterion_settled(
                    self._task.id,
                    entry.criterion_id,
                    statements.get(entry.criterion_id, ""),
                    entry.status,
                    entry.detail,
                )
            )

    async def _conclude(self) -> None:
        if self.state == COMPLETED:
            await self._clients.project.move_task(self._task.id, VERIFYING, None)
            await self._clients.project.move_task(self._task.id, DONE, None)

            return

        if self.state == AWAITING:
            await self._clients.project.move_task(self._task.id, AWAITING_CONFIRMATION, self.reason)

            return

        if self.state == FAILED:
            await self._clients.project.move_task(
                self._task.id, TASK_FAILED, self.reason or NOT_RUN
            )

    async def _percentages(self) -> tuple[float, float]:
        try:
            snapshot = await self._clients.project.progress(self._project_id)
        except UPSTREAM_FAILURES:
            return 0.0, 0.0

        return snapshot.of(self._task.id).percentage, snapshot.overall.percentage
