from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import events, stepstates
from project_service.models import (
    AcceptanceCriterionRow,
    ActionPlanRow,
    ActionStepRow,
    StepTransitionRow,
)
from project_service.tasks import get_task

STEP_STATES = frozenset(
    {
        "pending",
        "awaiting_confirmation",
        "running",
        "succeeded",
        "failed",
        "aborted",
        "never_attempted",
    }
)


class PlanNotFoundError(RuntimeError):
    def __init__(self, plan_id: str) -> None:
        super().__init__(f"plan {plan_id} does not exist")
        self.plan_id = plan_id


class StepNotFoundError(RuntimeError):
    def __init__(self, step_id: str) -> None:
        super().__init__(f"step {step_id} does not exist")
        self.step_id = step_id


class UnknownCriterionRefError(RuntimeError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"plan references criteria not on this task: {', '.join(missing)}")
        self.missing = missing


class EmptyPlanError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("a plan must contain at least one step")


async def criterion_ids(session: AsyncSession, task_id: str) -> set[str]:
    result = await session.execute(
        select(AcceptanceCriterionRow.id).where(AcceptanceCriterionRow.task_id == task_id)
    )

    return set(result.scalars().all())


def assert_refs(steps: list[dict[str, Any]], known: set[str]) -> None:
    missing: list[str] = []

    for step in steps:
        for ref in step.get("criterion_refs", []):
            if ref not in known and ref not in missing:
                missing.append(ref)

    if missing:
        raise UnknownCriterionRefError(missing)


async def create(
    session: AsyncSession, task_id: str, fields: dict[str, Any], steps: list[dict[str, Any]]
) -> ActionPlanRow:
    if not steps:
        raise EmptyPlanError

    task = await get_task(session, task_id)
    assert_refs(steps, await criterion_ids(session, task_id))

    plan = ActionPlanRow(
        project_id=task.project_id,
        task_id=task_id,
        request_id=str(fields["request_id"]),
        scope_root=str(fields["scope_root"]),
        intent=str(fields["intent"]),
        rationale=str(fields["rationale"]),
        target_engine_id=fields.get("target_engine_id"),
        target_model_id=fields.get("target_model_id"),
        steps_total=len(steps),
        gated_count=sum(1 for step in steps if step.get("requires_confirmation", True)),
        attempts=int(fields.get("attempts", 1)),
        repaired=bool(fields.get("repaired", False)),
        model_id=str(fields["model_id"]),
        prompt_name=str(fields["prompt_name"]),
        prompt_version=str(fields["prompt_version"]),
        prompt_hash=str(fields["prompt_hash"]),
    )
    session.add(plan)
    await session.flush()

    for position, step in enumerate(steps):
        session.add(
            ActionStepRow(
                plan_id=plan.id,
                position=position,
                description=str(step["description"]),
                service=str(step["service"]),
                action=step.get("action"),
                requires_confirmation=bool(step.get("requires_confirmation", True)),
                confirmation_reason=step.get("confirmation_reason"),
                on_failure=str(step.get("on_failure", "abort")),
                reversible=bool(step.get("reversible", False)),
                criterion_refs=list(step.get("criterion_refs", [])),
                effects=dict(step.get("effects", {})),
            )
        )

    task.action_plan_id = plan.id

    events.record(
        session,
        task.project_id,
        "plan.created",
        task_id=task_id,
        reason=f"{plan.steps_total} step(s), {plan.gated_count} gated",
        actor="router",
    )

    await session.commit()
    await session.refresh(plan)

    return plan


async def get(session: AsyncSession, plan_id: str) -> ActionPlanRow:
    row = await session.get(ActionPlanRow, plan_id)

    if row is None:
        raise PlanNotFoundError(plan_id)

    return row


async def get_step(session: AsyncSession, step_id: str) -> ActionStepRow:
    row = await session.get(ActionStepRow, step_id)

    if row is None:
        raise StepNotFoundError(step_id)

    return row


async def steps_for(session: AsyncSession, plan_id: str) -> list[ActionStepRow]:
    result = await session.execute(
        select(ActionStepRow)
        .where(ActionStepRow.plan_id == plan_id)
        .order_by(ActionStepRow.position.asc())
    )

    return list(result.scalars().all())


async def latest(session: AsyncSession, task_id: str) -> ActionPlanRow | None:
    await get_task(session, task_id)

    result = await session.execute(
        select(ActionPlanRow)
        .where(ActionPlanRow.task_id == task_id)
        .order_by(ActionPlanRow.created_at.desc())
        .limit(1)
    )

    return result.scalars().one_or_none()


async def list_for_task(session: AsyncSession, task_id: str) -> list[ActionPlanRow]:
    await get_task(session, task_id)

    result = await session.execute(
        select(ActionPlanRow)
        .where(ActionPlanRow.task_id == task_id)
        .order_by(ActionPlanRow.created_at.asc())
    )

    return list(result.scalars().all())


async def transition_step(
    session: AsyncSession,
    step_id: str,
    target: str,
    reason: str | None,
    actor: str,
) -> ActionStepRow:
    step = await get_step(session, step_id)
    plan = await get(session, step.plan_id)

    stepstates.assert_transition(step.state, target, reason)

    previous = step.state
    step.state = target

    session.add(
        StepTransitionRow(
            step_id=step.id,
            plan_id=plan.id,
            task_id=plan.task_id,
            from_state=previous,
            to_state=target,
            reason=reason,
            actor=actor,
        )
    )

    await session.commit()
    await session.refresh(step)

    return step


async def transitions_for_step(session: AsyncSession, step_id: str) -> list[StepTransitionRow]:
    await get_step(session, step_id)

    result = await session.execute(
        select(StepTransitionRow)
        .where(StepTransitionRow.step_id == step_id)
        .order_by(StepTransitionRow.occurred_at.asc())
    )

    return list(result.scalars().all())


async def transitions_for_task(session: AsyncSession, task_id: str) -> list[StepTransitionRow]:
    result = await session.execute(
        select(StepTransitionRow)
        .where(StepTransitionRow.task_id == task_id)
        .order_by(StepTransitionRow.occurred_at.asc())
    )

    return list(result.scalars().all())
