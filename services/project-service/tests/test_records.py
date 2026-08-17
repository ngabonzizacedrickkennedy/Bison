from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from project_service import plans, records, tasks
from project_service.models import (
    AcceptanceCriterionRow,
    Base,
    ProjectEventRow,
    ProjectRow,
    TaskNodeRow,
)
from project_service.reconcile import UnknownHaltReasonError, UnplannedStepError
from project_service.records import NoPlanToReconcileError, RecordNotFoundError


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TRIGGER reconciliation_record_no_update "
                "BEFORE UPDATE ON reconciliation_record "
                "BEGIN SELECT RAISE(ABORT, 'reconciliation_record is append-only'); END"
            )
        )
        await connection.execute(
            text(
                "CREATE TRIGGER step_outcome_no_update "
                "BEFORE UPDATE ON step_outcome "
                "BEGIN SELECT RAISE(ABORT, 'step_outcome is append-only'); END"
            )
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as opened:
        yield opened

    await engine.dispose()


async def seeded(session: AsyncSession) -> tuple[str, list[str]]:
    project = ProjectRow(
        name="Invoice Reconciler", goal="reconcile statements", project_type="code"
    )
    session.add(project)
    await session.flush()

    task = TaskNodeRow(
        project_id=project.id,
        title="Provision the reconciliation database",
        origin="user",
        kind="dev",
        assigned_role="mediator",
    )
    session.add(task)
    await session.flush()

    criteria = []

    for statement in ("the schema file exists", "the table is queryable"):
        criterion = AcceptanceCriterionRow(
            task_id=task.id, statement=statement, check_kind="file_exists"
        )
        session.add(criterion)
        criteria.append(criterion)

    await session.commit()

    return task.id, [criterion.id for criterion in criteria]


async def planned(session: AsyncSession, task_id: str, criterion_ids: list[str]) -> list[str]:
    fields: dict[str, Any] = {
        "request_id": "11111111-1111-1111-1111-111111111111",
        "scope_root": "C:\\Users\\cedrick\\bison-workspace",
        "intent": "dev_task",
        "rationale": "the task provisions a local database",
        "model_id": "qwen2.5-coder:7b",
        "prompt_name": "router",
        "prompt_version": "v3",
        "prompt_hash": "7d997b13170f",
    }
    steps: list[dict[str, Any]] = [
        {
            "description": "create the schema file",
            "service": "task-runner",
            "requires_confirmation": False,
            "on_failure": "abort",
            "reversible": True,
            "criterion_refs": [criterion_ids[0]],
            "effects": {},
        },
        {
            "description": "apply the schema",
            "service": "task-runner",
            "requires_confirmation": False,
            "on_failure": "abort",
            "reversible": False,
            "criterion_refs": [criterion_ids[1]],
            "effects": {},
        },
        {
            "description": "seed the fixture rows",
            "service": "task-runner",
            "requires_confirmation": True,
            "confirmation_reason": "reaches the network",
            "on_failure": "abort",
            "reversible": False,
            "criterion_refs": [],
            "effects": {},
        },
    ]

    plan = await plans.create(session, task_id, fields, steps)

    return [row.id for row in await plans.steps_for(session, plan.id)]


async def test_a_halt_writes_one_outcome_per_planned_step(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    step_ids = await planned(session, task_id, criterion_ids)

    record = await records.write(
        session,
        task_id,
        "22222222-2222-2222-2222-222222222222",
        "kill_switch",
        [
            {
                "step_id": step_ids[0],
                "state": "succeeded",
                "touched_paths": ["schema.sql"],
                "exit_code": 0,
                "started_at": "2026-08-17T09:00:00+00:00",
                "ended_at": "2026-08-17T09:00:04+00:00",
            },
            {"step_id": step_ids[1], "state": "running", "touched_paths": ["bison.db"]},
        ],
    )

    outcomes = await records.outcomes_for(session, record.id)

    assert record.steps_total == 3
    assert record.steps_completed == 1
    assert record.steps_never_attempted == 1
    assert [row.state for row in outcomes] == ["succeeded", "aborted", "never_attempted"]
    assert record.touched_paths == ["schema.sql", "bison.db"]


async def test_the_frozen_percentage_matches_the_progress_engine(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    step_ids = await planned(session, task_id, criterion_ids)

    await tasks.set_criterion_status(session, criterion_ids[0], "verified", None, "inspector")

    record = await records.write(
        session,
        task_id,
        "33333333-3333-3333-3333-333333333333",
        "step_failure",
        [{"step_id": step_ids[0], "state": "succeeded"}],
    )

    assert record.percentage_at_halt == 50.0
    assert record.criteria_verified_ids == [criterion_ids[0]]
    assert record.criteria_unverified_ids == [criterion_ids[1]]
    assert "Task is 50% verified." in record.plain_summary


async def test_verified_criteria_survive_a_failed_step(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    step_ids = await planned(session, task_id, criterion_ids)

    await tasks.set_criterion_status(session, criterion_ids[0], "verified", None, "inspector")

    record = await records.write(
        session,
        task_id,
        "44444444-4444-4444-4444-444444444444",
        "step_failure",
        [
            {"step_id": step_ids[0], "state": "succeeded"},
            {"step_id": step_ids[1], "state": "failed", "exit_code": 1},
        ],
    )

    assert record.criteria_verified_ids == [criterion_ids[0]]
    assert "Step 2 failed: apply the schema." in record.plain_summary


async def test_outcome_timestamps_are_stored_as_datetimes(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    step_ids = await planned(session, task_id, criterion_ids)

    record = await records.write(
        session,
        task_id,
        "55555555-5555-5555-5555-555555555555",
        "user_stop",
        [
            {
                "step_id": step_ids[0],
                "state": "succeeded",
                "started_at": "2026-08-17T09:00:00+00:00",
                "ended_at": "2026-08-17T09:00:04+00:00",
            }
        ],
    )

    first = (await records.outcomes_for(session, record.id))[0]

    assert first.started_at is not None
    assert first.ended_at is not None
    assert (first.ended_at - first.started_at).total_seconds() == 4.0


async def test_every_halt_writes_a_new_record(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    step_ids = await planned(session, task_id, criterion_ids)

    first = await records.write(
        session,
        task_id,
        "66666666-6666-6666-6666-666666666666",
        "kill_switch",
        [{"step_id": step_ids[0], "state": "succeeded"}],
    )
    second = await records.write(
        session,
        task_id,
        "77777777-7777-7777-7777-777777777777",
        "user_stop",
        [
            {"step_id": step_ids[0], "state": "succeeded"},
            {"step_id": step_ids[1], "state": "succeeded"},
        ],
    )

    history = await records.list_for_task(session, task_id)
    current = await records.latest(session, task_id)

    assert [row.id for row in history] == [first.id, second.id]
    assert current is not None
    assert current.id == second.id
    assert current.steps_completed == 2


async def test_a_halt_records_a_project_event_carrying_the_summary(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    step_ids = await planned(session, task_id, criterion_ids)

    record = await records.write(
        session,
        task_id,
        "88888888-8888-8888-8888-888888888888",
        "kill_switch",
        [{"step_id": step_ids[0], "state": "succeeded"}],
    )

    result = await session.execute(
        select(ProjectEventRow).where(ProjectEventRow.event_type == "halt.kill_switch")
    )
    event = result.scalars().one()

    assert event.task_id == task_id
    assert event.reason == record.plain_summary
    assert event.actor == "mediator"


async def test_a_record_cannot_be_rewritten(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    step_ids = await planned(session, task_id, criterion_ids)

    record = await records.write(
        session,
        task_id,
        "99999999-9999-9999-9999-999999999999",
        "kill_switch",
        [{"step_id": step_ids[0], "state": "succeeded"}],
    )

    with pytest.raises(DatabaseError):
        await session.execute(
            text("UPDATE reconciliation_record SET plain_summary = 'all fine' WHERE id = :id"),
            {"id": record.id},
        )

    await session.rollback()


async def test_an_outcome_for_a_step_outside_the_plan_raises(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    await planned(session, task_id, criterion_ids)

    with pytest.raises(UnplannedStepError):
        await records.write(
            session,
            task_id,
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "kill_switch",
            [{"step_id": "not-a-step", "state": "succeeded"}],
        )


async def test_an_unknown_halt_reason_never_reaches_the_database(session: AsyncSession) -> None:
    task_id, criterion_ids = await seeded(session)
    await planned(session, task_id, criterion_ids)

    with pytest.raises(UnknownHaltReasonError):
        await records.write(session, task_id, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "gave_up", [])

    assert await records.latest(session, task_id) is None


async def test_a_task_with_no_plan_cannot_be_reconciled(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    with pytest.raises(NoPlanToReconcileError):
        await records.write(
            session, task_id, "cccccccc-cccc-cccc-cccc-cccccccccccc", "kill_switch", []
        )


async def test_an_unknown_record_id_raises(session: AsyncSession) -> None:
    with pytest.raises(RecordNotFoundError):
        await records.get(session, "dddddddd-dddd-dddd-dddd-dddddddddddd")
