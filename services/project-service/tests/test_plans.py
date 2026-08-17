from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from project_service import plans
from project_service.models import (
    AcceptanceCriterionRow,
    Base,
    ProjectEventRow,
    ProjectRow,
    TaskNodeRow,
)
from project_service.plans import (
    EmptyPlanError,
    PlanNotFoundError,
    StepNotFoundError,
    UnknownCriterionRefError,
)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as opened:
        yield opened

    await engine.dispose()


async def seeded(session: AsyncSession) -> tuple[str, str]:
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

    criterion = AcceptanceCriterionRow(
        task_id=task.id,
        statement="the schema file exists",
        check_kind="file_exists",
    )
    session.add(criterion)
    await session.commit()

    return task.id, criterion.id


def plan_fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "request_id": "11111111-1111-1111-1111-111111111111",
        "scope_root": "C:\\Users\\cedrick\\bison-workspace",
        "intent": "dev_task",
        "rationale": "the task provisions a local database",
        "model_id": "qwen2.5-coder:7b",
        "prompt_name": "router",
        "prompt_version": "v3",
        "prompt_hash": "7d997b13170f",
    }
    base.update(overrides)
    return base


def step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "description": "create the schema file",
        "service": "task-runner",
        "requires_confirmation": False,
        "confirmation_reason": None,
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": [],
        "effects": {"writes_paths": ["ledger.db"], "network": False},
    }
    base.update(overrides)
    return base


async def test_create_writes_plan_and_steps_in_order(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    plan = await plans.create(
        session,
        task_id,
        plan_fields(),
        [step(description="first"), step(description="second"), step(description="third")],
    )
    stored = await plans.steps_for(session, plan.id)

    assert plan.steps_total == 3
    assert [row.position for row in stored] == [0, 1, 2]
    assert [row.description for row in stored] == ["first", "second", "third"]


async def test_create_counts_gated_steps(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    plan = await plans.create(
        session,
        task_id,
        plan_fields(),
        [
            step(requires_confirmation=True, confirmation_reason="writes outside scope"),
            step(requires_confirmation=False),
            step(requires_confirmation=True, confirmation_reason="irreversible"),
        ],
    )

    assert plan.gated_count == 2


async def test_a_step_without_declarations_is_stored_gated(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    plan = await plans.create(
        session,
        task_id,
        plan_fields(),
        [{"description": "unknown work", "service": "task-runner"}],
    )
    stored = await plans.steps_for(session, plan.id)

    assert stored[0].requires_confirmation is True
    assert stored[0].reversible is False
    assert stored[0].on_failure == "abort"
    assert plan.gated_count == 1


async def test_effects_are_stored_whole(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)
    declared = {
        "writes_paths": ["ledger.db"],
        "deletes_paths": [],
        "network": True,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }

    plan = await plans.create(session, task_id, plan_fields(), [step(effects=declared)])
    stored = await plans.steps_for(session, plan.id)

    assert stored[0].effects == declared


async def test_create_accepts_a_real_criterion_reference(session: AsyncSession) -> None:
    task_id, criterion_id = await seeded(session)

    plan = await plans.create(
        session, task_id, plan_fields(), [step(criterion_refs=[criterion_id])]
    )
    stored = await plans.steps_for(session, plan.id)

    assert stored[0].criterion_refs == [criterion_id]


async def test_create_rejects_an_invented_criterion_reference(session: AsyncSession) -> None:
    task_id, criterion_id = await seeded(session)

    with pytest.raises(UnknownCriterionRefError) as error:
        await plans.create(
            session,
            task_id,
            plan_fields(),
            [step(criterion_refs=[criterion_id]), step(criterion_refs=["not-a-criterion"])],
        )

    assert error.value.missing == ["not-a-criterion"]


async def test_create_rejects_an_empty_plan(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    with pytest.raises(EmptyPlanError):
        await plans.create(session, task_id, plan_fields(), [])


async def test_create_points_the_task_at_the_plan(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    plan = await plans.create(session, task_id, plan_fields(), [step()])
    task = await session.get(TaskNodeRow, task_id)

    assert task is not None
    assert task.action_plan_id == plan.id


async def test_create_records_a_router_event(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    await plans.create(
        session, task_id, plan_fields(), [step(requires_confirmation=True, confirmation_reason="x")]
    )
    result = await session.execute(
        select(ProjectEventRow).where(ProjectEventRow.event_type == "plan.created")
    )
    event = result.scalars().one()

    assert event.task_id == task_id
    assert event.actor == "router"
    assert "1 gated" in (event.reason or "")


async def test_replanning_appends_rather_than_replaces(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    first = await plans.create(session, task_id, plan_fields(), [step(description="first pass")])
    second = await plans.create(session, task_id, plan_fields(), [step(description="second pass")])
    history = await plans.list_for_task(session, task_id)
    current = await plans.latest(session, task_id)

    assert [row.id for row in history] == [first.id, second.id]
    assert current is not None
    assert current.id == second.id


async def test_steps_are_addressable_by_id(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    plan = await plans.create(session, task_id, plan_fields(), [step(), step()])
    stored = await plans.steps_for(session, plan.id)
    resolved = await plans.get_step(session, stored[1].id)

    assert resolved.plan_id == plan.id
    assert resolved.position == 1


async def test_missing_plan_and_step_name_themselves(session: AsyncSession) -> None:
    with pytest.raises(PlanNotFoundError, match="ghost-plan"):
        await plans.get(session, "ghost-plan")

    with pytest.raises(StepNotFoundError, match="ghost-step"):
        await plans.get_step(session, "ghost-step")


async def test_latest_is_none_before_any_plan(session: AsyncSession) -> None:
    task_id, _ = await seeded(session)

    assert await plans.latest(session, task_id) is None
