from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from project_service import plans
from project_service.api import to_step
from project_service.models import Base, ProjectRow, TaskNodeRow

WRITE_FILE: dict[str, Any] = {
    "type": "write_file",
    "path": "C:\\scope\\reconcile.py",
    "content": "def reconcile():\n    return []\n",
}

INSTALL: dict[str, Any] = {"type": "install_python_packages", "packages": ["fastapi"]}


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
        title="Write the reconciliation module",
        origin="mediator",
        kind="dev",
        assigned_role="engine",
    )
    session.add(task)
    await session.commit()

    return str(task.id)


def step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "description": "Write the reconciliation module",
        "service": "task-runner",
        "action": WRITE_FILE,
        "requires_confirmation": False,
        "confirmation_reason": None,
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": [],
        "effects": {"writes_paths": ["C:\\scope\\reconcile.py"]},
    }
    base.update(overrides)

    return base


async def planned(session: AsyncSession, *steps: dict[str, Any]) -> list[Any]:
    task_id = await seeded(session)

    plan = await plans.create(
        session,
        task_id,
        {
            "request_id": "11111111-1111-1111-1111-111111111111",
            "scope_root": "C:\\scope",
            "intent": "dev_task",
            "rationale": "the task asks for a module",
            "attempts": 1,
            "repaired": False,
            "model_id": "qwen2.5-coder:7b",
            "prompt_name": "router",
            "prompt_version": "v4",
            "prompt_hash": "d9223d1149c4",
        },
        list(steps),
    )

    return list(await plans.steps_for(session, plan.id))


async def test_a_stored_step_returns_the_action_it_was_given(session: AsyncSession) -> None:
    rows = await planned(session, step())

    assert to_step(rows[0]).action == WRITE_FILE


async def test_the_content_of_a_written_file_survives_storage(session: AsyncSession) -> None:
    body = "import os\n\n\nprint(len(os.listdir('.')))\n"
    rows = await planned(session, step(action={**WRITE_FILE, "content": body}))
    stored = to_step(rows[0]).action

    assert stored is not None
    assert stored["content"] == body


async def test_a_step_for_another_service_stores_no_action(session: AsyncSession) -> None:
    rows = await planned(session, step(service="dev-env", action=None))
    read = to_step(rows[0])

    assert read.action is None
    assert "action" in read.model_dump()


async def test_an_absent_action_reads_as_none_rather_than_raising(
    session: AsyncSession,
) -> None:
    bare = step()
    del bare["action"]

    rows = await planned(session, bare)

    assert to_step(rows[0]).action is None


async def test_each_step_keeps_its_own_action(session: AsyncSession) -> None:
    rows = await planned(session, step(), step(action=INSTALL))
    actions = [to_step(row).action for row in rows]

    assert actions[0] == WRITE_FILE
    assert actions[1] == INSTALL


async def test_a_package_list_survives_as_a_list(session: AsyncSession) -> None:
    rows = await planned(
        session, step(action={"type": "install_python_packages", "packages": ["a", "b"]})
    )
    stored = to_step(rows[0]).action

    assert stored is not None
    assert stored["packages"] == ["a", "b"]


async def test_the_action_reaches_the_wire_and_not_only_the_model(
    session: AsyncSession,
) -> None:
    rows = await planned(session, step())

    assert to_step(rows[0]).model_dump(mode="json")["action"] == WRITE_FILE
