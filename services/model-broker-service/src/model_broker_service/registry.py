from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model_broker_service.models import RoleBindingRow, new_id, utc_now

Role = Literal["analyst", "engine", "mediator", "inspector"]

ROLES: tuple[Role, ...] = ("analyst", "engine", "mediator", "inspector")

DEFAULT_LOCAL_MODEL = "qwen2.5-coder:7b"
DEFAULT_REMOTE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

DEFAULT_BINDINGS: dict[Role, tuple[str, str]] = {
    "analyst": (DEFAULT_REMOTE_MODEL, "remote"),
    "engine": (DEFAULT_REMOTE_MODEL, "remote"),
    "mediator": (DEFAULT_LOCAL_MODEL, "local"),
    "inspector": (DEFAULT_LOCAL_MODEL, "local"),
}

PROMPT_VERSIONS: dict[Role, str] = {
    "analyst": "v1",
    "engine": "v1",
    "mediator": "v1",
    "inspector": "v1",
}


class RoleRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_bindings(self, project_id: str) -> list[RoleBindingRow]:
        await self.ensure_defaults(project_id)

        result = await self._session.execute(
            select(RoleBindingRow)
            .where(RoleBindingRow.project_id == project_id)
            .order_by(RoleBindingRow.role.asc())
        )

        return list(result.scalars().all())

    async def get_binding(self, project_id: str, role: Role) -> RoleBindingRow:
        await self.ensure_defaults(project_id)

        result = await self._session.execute(
            select(RoleBindingRow).where(
                RoleBindingRow.project_id == project_id,
                RoleBindingRow.role == role,
            )
        )

        row = result.scalar_one_or_none()

        if row is None:
            raise LookupError(f"no binding for role {role} in project {project_id}")

        return row

    async def bind(
        self,
        project_id: str,
        role: Role,
        model_id: str,
        locality: str,
        engine_id: str | None,
    ) -> RoleBindingRow:
        row = await self.get_binding(project_id, role)

        row.model_id = model_id
        row.locality = locality
        row.engine_id = engine_id
        row.prompt_version = PROMPT_VERSIONS[role]
        row.bound_at = utc_now()

        await self._session.commit()
        await self._session.refresh(row)

        return row

    async def ensure_defaults(self, project_id: str) -> None:
        result = await self._session.execute(
            select(RoleBindingRow.role).where(RoleBindingRow.project_id == project_id)
        )

        existing = set(result.scalars().all())
        missing = [role for role in ROLES if role not in existing]

        if not missing:
            return

        for role in missing:
            model_id, locality = DEFAULT_BINDINGS[role]

            self._session.add(
                RoleBindingRow(
                    id=new_id(),
                    project_id=project_id,
                    role=role,
                    model_id=model_id,
                    engine_id=None,
                    locality=locality,
                    prompt_version=PROMPT_VERSIONS[role],
                    bound_at=utc_now(),
                )
            )

        await self._session.commit()
