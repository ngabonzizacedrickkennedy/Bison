from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import events, progress
from project_service.models import AcceptanceCriterionRow, TaskNodeRow, utc_now
from project_service.projects import get as get_project
from project_service.taskstates import assert_transition


class TaskNotFoundError(RuntimeError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task {task_id} does not exist")
        self.task_id = task_id


class CriterionNotFoundError(RuntimeError):
    def __init__(self, criterion_id: str) -> None:
        super().__init__(f"criterion {criterion_id} does not exist")
        self.criterion_id = criterion_id


class UnknownDependencyError(RuntimeError):
    def __init__(self, task_id: str, missing: list[str]) -> None:
        super().__init__(f"task {task_id} depends on unknown tasks: {', '.join(missing)}")
        self.missing = missing


class ParentOutsideProjectError(RuntimeError):
    def __init__(self, parent_id: str) -> None:
        super().__init__(f"parent task {parent_id} belongs to a different project")
        self.parent_id = parent_id


async def list_tasks(session: AsyncSession, project_id: str) -> list[TaskNodeRow]:
    result = await session.execute(
        select(TaskNodeRow)
        .where(TaskNodeRow.project_id == project_id)
        .order_by(TaskNodeRow.position.asc(), TaskNodeRow.created_at.asc())
    )
    return list(result.scalars().all())


async def list_criteria(session: AsyncSession, project_id: str) -> list[AcceptanceCriterionRow]:
    result = await session.execute(
        select(AcceptanceCriterionRow)
        .join(TaskNodeRow, TaskNodeRow.id == AcceptanceCriterionRow.task_id)
        .where(TaskNodeRow.project_id == project_id)
    )
    return list(result.scalars().all())


async def get_task(session: AsyncSession, task_id: str) -> TaskNodeRow:
    row = await session.get(TaskNodeRow, task_id)

    if row is None:
        raise TaskNotFoundError(task_id)

    return row


async def get_criterion(session: AsyncSession, criterion_id: str) -> AcceptanceCriterionRow:
    row = await session.get(AcceptanceCriterionRow, criterion_id)

    if row is None:
        raise CriterionNotFoundError(criterion_id)

    return row


async def create_task(
    session: AsyncSession, project_id: str, fields: dict[str, Any]
) -> TaskNodeRow:
    await get_project(session, project_id)

    parent_id = fields.get("parent_id")

    if parent_id is not None:
        parent = await get_task(session, str(parent_id))

        if parent.project_id != project_id:
            raise ParentOutsideProjectError(str(parent_id))

    depends_on = [str(item) for item in fields.get("depends_on", [])]

    if depends_on:
        siblings = {row.id for row in await list_tasks(session, project_id)}
        missing = [item for item in depends_on if item not in siblings]

        if missing:
            raise UnknownDependencyError(project_id, missing)

    row = TaskNodeRow(project_id=project_id, **fields)
    session.add(row)
    await session.flush()

    events.record(
        session,
        project_id,
        "task.created",
        task_id=row.id,
        to_state=row.state,
        actor="user",
    )

    await session.commit()
    await session.refresh(row)
    return row


async def transition_task(
    session: AsyncSession, task_id: str, target: str, reason: str | None, actor: str
) -> TaskNodeRow:
    row = await get_task(session, task_id)
    assert_transition(row.state, target, reason)

    events.record(
        session,
        row.project_id,
        f"task.{target}",
        task_id=row.id,
        from_state=row.state,
        to_state=target,
        reason=reason,
        actor=actor,
    )

    row.state = target
    row.state_reason = reason

    await session.commit()
    await session.refresh(row)
    return row


async def create_criterion(
    session: AsyncSession, task_id: str, fields: dict[str, Any]
) -> AcceptanceCriterionRow:
    task = await get_task(session, task_id)

    row = AcceptanceCriterionRow(task_id=task_id, **fields)
    session.add(row)
    await session.flush()

    events.record(
        session,
        task.project_id,
        "criterion.created",
        task_id=task_id,
        criterion_id=row.id,
        to_state=row.status,
        actor="user",
    )

    await session.commit()
    await session.refresh(row)
    return row


async def set_criterion_status(
    session: AsyncSession,
    criterion_id: str,
    status: str,
    reason: str | None,
    actor: str,
) -> AcceptanceCriterionRow:
    row = await get_criterion(session, criterion_id)
    task = await get_task(session, row.task_id)

    previous = row.status

    events.record(
        session,
        task.project_id,
        f"criterion.{status}",
        task_id=task.id,
        criterion_id=row.id,
        from_state=previous,
        to_state=status,
        reason=reason,
        actor=actor,
    )

    row.status = status
    row.status_reason = reason
    row.verified_at = utc_now() if status == "verified" else None
    row.verified_by = actor if status == "verified" else None

    await session.commit()
    await session.refresh(row)
    return row


async def snapshot(session: AsyncSession, project_id: str) -> dict[str, progress.Progress]:
    await get_project(session, project_id)

    tasks = [
        progress.Task(id=row.id, parent_id=row.parent_id, state=row.state)
        for row in await list_tasks(session, project_id)
    ]
    criteria = [
        progress.Criterion(id=row.id, task_id=row.task_id, weight=row.weight, status=row.status)
        for row in await list_criteria(session, project_id)
    ]

    return progress.compute(tasks, criteria)
