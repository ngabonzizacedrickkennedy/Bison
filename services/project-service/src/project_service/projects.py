from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import events
from project_service.config import settings
from project_service.lifecycle import EVENT_NAMES, OPEN_STATES, assert_transition
from project_service.models import ProjectEventRow, ProjectRow, utc_now


class ProjectNotFoundError(RuntimeError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"project {project_id} does not exist")
        self.project_id = project_id


class ProjectCapReachedError(RuntimeError):
    def __init__(self, open_projects: int, cap: int) -> None:
        super().__init__(
            f"{open_projects} of {cap} non-archived projects already exist; "
            "archive one before creating another"
        )
        self.open_projects = open_projects
        self.cap = cap


async def count_open(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(ProjectRow).where(ProjectRow.state.in_(OPEN_STATES))
    )
    return int(result.scalar_one())


async def get(session: AsyncSession, project_id: str) -> ProjectRow:
    row = await session.get(ProjectRow, project_id)

    if row is None:
        raise ProjectNotFoundError(project_id)

    return row


async def list_projects(session: AsyncSession, state: str | None) -> list[ProjectRow]:
    statement = select(ProjectRow).order_by(ProjectRow.created_at.asc())

    if state is not None:
        statement = statement.where(ProjectRow.state == state)

    result = await session.execute(statement)
    return list(result.scalars().all())


async def active_project(session: AsyncSession) -> ProjectRow | None:
    result = await session.execute(select(ProjectRow).where(ProjectRow.state == "active"))
    return result.scalars().first()


async def list_events(session: AsyncSession, project_id: str, limit: int) -> list[ProjectEventRow]:
    result = await session.execute(
        select(ProjectEventRow)
        .where(ProjectEventRow.project_id == project_id)
        .order_by(ProjectEventRow.occurred_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def create(session: AsyncSession, fields: dict[str, Any]) -> ProjectRow:
    cap = settings().max_projects
    open_projects = await count_open(session)

    if open_projects >= cap:
        raise ProjectCapReachedError(open_projects, cap)

    row = ProjectRow(**fields, state="draft")
    session.add(row)
    await session.flush()

    events.record(session, row.id, "project.created", to_state="draft")

    await session.commit()
    await session.refresh(row)
    return row


async def update(session: AsyncSession, project_id: str, changes: dict[str, Any]) -> ProjectRow:
    row = await get(session, project_id)

    if not changes:
        return row

    for key, value in changes.items():
        setattr(row, key, value)

    events.record(session, row.id, "project.updated", reason=", ".join(sorted(changes)))

    await session.commit()
    await session.refresh(row)
    return row


async def transition(
    session: AsyncSession,
    project_id: str,
    target: str,
    reason: str | None,
    actor: str,
) -> ProjectRow:
    row = await get(session, project_id)
    assert_transition(row.state, target)

    if target == "active":
        incumbent = await active_project(session)

        if incumbent is not None and incumbent.id != row.id:
            assert_transition(incumbent.state, "paused")
            events.record(
                session,
                incumbent.id,
                EVENT_NAMES["paused"],
                from_state=incumbent.state,
                to_state="paused",
                reason=f"switched to project {row.id}",
                actor=actor,
            )
            incumbent.state = "paused"
            await session.flush()

    if target == "archived":
        row.archived_at = utc_now()

    events.record(
        session,
        row.id,
        EVENT_NAMES[target],
        from_state=row.state,
        to_state=target,
        reason=reason,
        actor=actor,
    )

    row.state = target

    await session.commit()
    await session.refresh(row)
    return row
