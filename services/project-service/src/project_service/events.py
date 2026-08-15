from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from project_service.models import ProjectEventRow


def record(
    session: AsyncSession,
    project_id: str,
    event_type: str,
    *,
    task_id: str | None = None,
    criterion_id: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    reason: str | None = None,
    actor: str = "user",
) -> ProjectEventRow:
    event = ProjectEventRow(
        project_id=project_id,
        event_type=event_type,
        task_id=task_id,
        criterion_id=criterion_id,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        actor=actor,
    )
    session.add(event)
    return event
