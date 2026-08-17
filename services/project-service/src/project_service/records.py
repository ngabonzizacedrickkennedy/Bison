from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import events, plans, progress, reconcile
from project_service.models import (
    AcceptanceCriterionRow,
    ReconciliationRecordRow,
    StepOutcomeRow,
    TaskNodeRow,
)
from project_service.tasks import get_task


class RecordNotFoundError(RuntimeError):
    def __init__(self, record_id: str) -> None:
        super().__init__(f"reconciliation record {record_id} does not exist")
        self.record_id = record_id


class NoPlanToReconcileError(RuntimeError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task {task_id} has no action plan to reconcile")
        self.task_id = task_id


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    return datetime.fromisoformat(str(value))


async def _task_percentage(session: AsyncSession, task: TaskNodeRow) -> float:
    tasks = [
        progress.Task(id=row.id, parent_id=row.parent_id, state=row.state)
        for row in (
            await session.execute(
                select(TaskNodeRow).where(TaskNodeRow.project_id == task.project_id)
            )
        )
        .scalars()
        .all()
    ]
    criteria = [
        progress.Criterion(id=row.id, task_id=row.task_id, weight=row.weight, status=row.status)
        for row in (
            await session.execute(
                select(AcceptanceCriterionRow)
                .join(TaskNodeRow, TaskNodeRow.id == AcceptanceCriterionRow.task_id)
                .where(TaskNodeRow.project_id == task.project_id)
            )
        )
        .scalars()
        .all()
    ]

    computed = progress.compute(tasks, criteria)
    own = computed.get(task.id)

    return 0.0 if own is None else own.percentage


async def _task_criteria(session: AsyncSession, task_id: str) -> list[reconcile.CriterionState]:
    result = await session.execute(
        select(AcceptanceCriterionRow).where(AcceptanceCriterionRow.task_id == task_id)
    )

    return [reconcile.CriterionState(id=row.id, status=row.status) for row in result.scalars()]


async def _planned_steps(session: AsyncSession, plan_id: str) -> list[reconcile.PlannedStep]:
    rows = await plans.steps_for(session, plan_id)

    return [
        reconcile.PlannedStep(step_id=row.id, position=row.position, description=row.description)
        for row in rows
    ]


def _recorded(outcomes: list[dict[str, Any]]) -> list[reconcile.RecordedOutcome]:
    return [
        reconcile.RecordedOutcome(
            step_id=str(outcome["step_id"]),
            state=str(outcome["state"]),
            touched_paths=[str(path) for path in outcome.get("touched_paths", [])],
            exit_code=outcome.get("exit_code"),
            error_message=outcome.get("error_message"),
            started_at=outcome.get("started_at"),
            ended_at=outcome.get("ended_at"),
        )
        for outcome in outcomes
    ]


async def write(
    session: AsyncSession,
    task_id: str,
    request_id: str,
    halt_reason: str,
    outcomes: list[dict[str, Any]],
) -> ReconciliationRecordRow:
    reconcile.assert_halt_reason(halt_reason)

    task = await get_task(session, task_id)
    plan = await plans.latest(session, task_id)

    if plan is None:
        raise NoPlanToReconcileError(task_id)

    percentage = await _task_percentage(session, task)

    settled = reconcile.reconcile(
        request_id=request_id,
        task_id=task_id,
        halt_reason=halt_reason,
        steps=await _planned_steps(session, plan.id),
        outcomes=_recorded(outcomes),
        criteria=await _task_criteria(session, task_id),
        percentage=percentage,
    )

    record = ReconciliationRecordRow(
        project_id=task.project_id,
        task_id=task_id,
        plan_id=plan.id,
        request_id=request_id,
        halt_reason=halt_reason,
        steps_total=settled.steps_total,
        steps_completed=settled.steps_completed,
        steps_never_attempted=settled.steps_never_attempted,
        criteria_verified_ids=list(settled.criteria_verified_ids),
        criteria_unverified_ids=list(settled.criteria_unverified_ids),
        touched_paths=list(settled.touched_paths),
        percentage_at_halt=percentage,
        plain_summary=settled.plain_summary,
    )
    session.add(record)
    await session.flush()

    for outcome in settled.step_outcomes:
        session.add(
            StepOutcomeRow(
                record_id=record.id,
                step_id=outcome.step_id,
                position=outcome.position,
                description=outcome.description,
                state=outcome.state,
                touched_paths=list(outcome.touched_paths),
                exit_code=outcome.exit_code,
                error_message=outcome.error_message,
                started_at=_timestamp(outcome.started_at),
                ended_at=_timestamp(outcome.ended_at),
            )
        )

    events.record(
        session,
        task.project_id,
        f"halt.{halt_reason}",
        task_id=task_id,
        reason=settled.plain_summary,
        actor="mediator",
    )

    await session.commit()
    await session.refresh(record)

    return record


async def get(session: AsyncSession, record_id: str) -> ReconciliationRecordRow:
    row = await session.get(ReconciliationRecordRow, record_id)

    if row is None:
        raise RecordNotFoundError(record_id)

    return row


async def outcomes_for(session: AsyncSession, record_id: str) -> list[StepOutcomeRow]:
    result = await session.execute(
        select(StepOutcomeRow)
        .where(StepOutcomeRow.record_id == record_id)
        .order_by(StepOutcomeRow.position.asc())
    )

    return list(result.scalars().all())


async def latest(session: AsyncSession, task_id: str) -> ReconciliationRecordRow | None:
    await get_task(session, task_id)

    result = await session.execute(
        select(ReconciliationRecordRow)
        .where(ReconciliationRecordRow.task_id == task_id)
        .order_by(ReconciliationRecordRow.written_at.desc())
        .limit(1)
    )

    return result.scalars().one_or_none()


async def list_for_task(session: AsyncSession, task_id: str) -> list[ReconciliationRecordRow]:
    await get_task(session, task_id)

    result = await session.execute(
        select(ReconciliationRecordRow)
        .where(ReconciliationRecordRow.task_id == task_id)
        .order_by(ReconciliationRecordRow.written_at.asc())
    )

    return list(result.scalars().all())
