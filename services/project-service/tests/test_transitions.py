from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from project_service import plans
from project_service.models import AcceptanceCriterionRow, Base, ProjectRow, TaskNodeRow
from project_service.stepstates import IllegalStepTransitionError, StepReasonRequiredError


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TRIGGER step_transition_no_update "
                "BEFORE UPDATE ON step_transition "
                "BEGIN SELECT RAISE(ABORT, 'step_transition is append-only'); END"
            )
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as opened:
        yield opened

    await engine.dispose()


async def planned(session: AsyncSession) -> tuple[str, list[str]]:
    project = ProjectRow(name="Transitions", goal="exercise step states", project_type="code")
    session.add(project)
    await session.flush()

    task = TaskNodeRow(
        project_id=project.id,
        title="Provision the reconciliation database",
        origin="user",
        kind="dev",
        assigned_role="engine",
    )
    session.add(task)
    await session.flush()

    criterion = AcceptanceCriterionRow(
        task_id=task.id, statement="the schema file exists", check_kind="file_exists"
    )
    session.add(criterion)
    await session.commit()

    fields: dict[str, Any] = {
        "request_id": "11111111-1111-1111-1111-111111111111",
        "scope_root": "C:\\workspace",
        "intent": "dev_task",
        "rationale": "provisions a local database",
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
            "on_failure": "retry",
            "reversible": True,
            "criterion_refs": [criterion.id],
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

    plan = await plans.create(session, task.id, fields, steps)

    return task.id, [row.id for row in await plans.steps_for(session, plan.id)]


async def test_a_transition_writes_the_column_and_the_log_together(session: AsyncSession) -> None:
    task_id, step_ids = await planned(session)

    step = await plans.transition_step(session, step_ids[0], "running", None, "task-runner")
    log = await plans.transitions_for_step(session, step_ids[0])

    assert step.state == "running"
    assert len(log) == 1
    assert log[0].from_state == "pending"
    assert log[0].to_state == "running"
    assert log[0].actor == "task-runner"
    assert log[0].task_id == task_id
    assert log[0].occurred_at is not None


async def test_every_transition_appends_rather_than_replacing(session: AsyncSession) -> None:
    _, step_ids = await planned(session)

    await plans.transition_step(session, step_ids[0], "running", None, "task-runner")
    await plans.transition_step(session, step_ids[0], "failed", "exit code 1", "task-runner")
    await plans.transition_step(session, step_ids[0], "running", None, "task-runner")
    step = await plans.transition_step(session, step_ids[0], "succeeded", None, "task-runner")

    log = await plans.transitions_for_step(session, step_ids[0])

    assert step.state == "succeeded"
    assert [row.to_state for row in log] == ["running", "failed", "running", "succeeded"]
    assert log[1].reason == "exit code 1"
    assert log[3].reason is None


async def test_a_halt_aborts_the_running_step_and_leaves_the_rest_pending(
    session: AsyncSession,
) -> None:
    task_id, step_ids = await planned(session)

    await plans.transition_step(session, step_ids[0], "running", None, "task-runner")
    aborted = await plans.transition_step(
        session, step_ids[0], "aborted", "halted by kill switch", "user"
    )
    untouched = await plans.get_step(session, step_ids[1])

    assert aborted.state == "aborted"
    assert untouched.state == "pending"
    assert len(await plans.transitions_for_task(session, task_id)) == 2


async def test_a_gated_step_records_its_confirmation_wait(session: AsyncSession) -> None:
    _, step_ids = await planned(session)

    await plans.transition_step(session, step_ids[1], "awaiting_confirmation", None, "task-runner")
    step = await plans.transition_step(session, step_ids[1], "running", None, "user")

    log = await plans.transitions_for_step(session, step_ids[1])

    assert step.state == "running"
    assert [row.to_state for row in log] == ["awaiting_confirmation", "running"]
    assert log[1].actor == "user"


async def test_an_illegal_transition_writes_nothing(session: AsyncSession) -> None:
    _, step_ids = await planned(session)

    with pytest.raises(IllegalStepTransitionError):
        await plans.transition_step(session, step_ids[0], "succeeded", None, "task-runner")

    step = await plans.get_step(session, step_ids[0])

    assert step.state == "pending"
    assert await plans.transitions_for_step(session, step_ids[0]) == []


async def test_a_missing_reason_writes_nothing(session: AsyncSession) -> None:
    _, step_ids = await planned(session)

    await plans.transition_step(session, step_ids[0], "running", None, "task-runner")

    with pytest.raises(StepReasonRequiredError):
        await plans.transition_step(session, step_ids[0], "failed", None, "task-runner")

    step = await plans.get_step(session, step_ids[0])

    assert step.state == "running"
    assert len(await plans.transitions_for_step(session, step_ids[0])) == 1


async def test_a_recorded_transition_cannot_be_rewritten(session: AsyncSession) -> None:
    _, step_ids = await planned(session)

    await plans.transition_step(session, step_ids[0], "running", None, "task-runner")

    with pytest.raises(DatabaseError):
        await session.execute(text("UPDATE step_transition SET to_state = 'succeeded'"))

    await session.rollback()


async def test_transitions_for_a_task_span_all_its_steps(session: AsyncSession) -> None:
    task_id, step_ids = await planned(session)

    await plans.transition_step(session, step_ids[0], "running", None, "task-runner")
    await plans.transition_step(session, step_ids[0], "succeeded", None, "task-runner")
    await plans.transition_step(session, step_ids[1], "awaiting_confirmation", None, "task-runner")

    log = await plans.transitions_for_task(session, task_id)

    assert [row.to_state for row in log] == ["running", "succeeded", "awaiting_confirmation"]
