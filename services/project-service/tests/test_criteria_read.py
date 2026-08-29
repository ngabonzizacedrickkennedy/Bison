from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from project_service import tasks
from project_service.api import CriterionRead
from project_service.models import Base, ProjectRow, TaskNodeRow

DETERMINISTIC_SPEC: dict[str, Any] = {
    "type": "file_exists",
    "path": "C:\\Users\\cedrick\\bison-workspace\\schema.sql",
}


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as opened:
        yield opened

    await engine.dispose()


async def seeded(session: AsyncSession) -> str:
    project = ProjectRow(
        name="Invoice Reconciler", goal="reconcile statements", project_type="code"
    )
    session.add(project)
    await session.flush()

    task = TaskNodeRow(
        project_id=project.id,
        title="Provision the reconciliation database",
        origin="mediator",
        kind="setup",
        assigned_role="engine",
    )
    session.add(task)
    await session.commit()

    return str(task.id)


async def criterion_of(
    session: AsyncSession, task_id: str, spec: dict[str, Any] | None, kind: str
) -> CriterionRead:
    row = await tasks.create_criterion(
        session,
        task_id,
        {
            "statement": "the schema file exists",
            "check_kind": kind,
            "check_spec": spec,
            "weight": 1,
        },
    )

    return CriterionRead.model_validate(row, from_attributes=True)


async def test_a_created_criterion_reports_the_spec_it_was_given(
    session: AsyncSession,
) -> None:
    task_id = await seeded(session)
    read = await criterion_of(session, task_id, DETERMINISTIC_SPEC, "deterministic")

    assert read.check_spec == DETERMINISTIC_SPEC


async def test_a_listed_criterion_carries_the_spec_a_check_would_need(
    session: AsyncSession,
) -> None:
    task_id = await seeded(session)
    await criterion_of(session, task_id, DETERMINISTIC_SPEC, "deterministic")

    task = await tasks.get_task(session, task_id)
    rows = [c for c in await tasks.list_criteria(session, task.project_id) if c.task_id == task_id]
    read = [CriterionRead.model_validate(row, from_attributes=True) for row in rows]

    assert len(read) == 1
    assert read[0].check_spec == DETERMINISTIC_SPEC


async def test_the_spec_survives_a_status_change(session: AsyncSession) -> None:
    task_id = await seeded(session)
    created = await criterion_of(session, task_id, DETERMINISTIC_SPEC, "deterministic")

    row = await tasks.set_criterion_status(session, created.id, "verified", None, "mediator")
    read = CriterionRead.model_validate(row, from_attributes=True)

    assert read.status == "verified"
    assert read.check_spec == DETERMINISTIC_SPEC


async def test_an_inspected_criterion_reports_no_spec_rather_than_dropping_the_field(
    session: AsyncSession,
) -> None:
    task_id = await seeded(session)
    read = await criterion_of(session, task_id, None, "inspected")

    assert "check_spec" in read.model_dump()
    assert read.check_spec is None


async def test_the_spec_reaches_the_wire_and_not_only_the_model(
    session: AsyncSession,
) -> None:
    task_id = await seeded(session)
    read = await criterion_of(session, task_id, DETERMINISTIC_SPEC, "deterministic")

    assert read.model_dump(mode="json")["check_spec"] == DETERMINISTIC_SPEC
