from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import events
from project_service.conceiveblocks import (
    ConceiveBlock,
    FileRefBlock,
    ImageBlock,
    parse_blocks,
    project_references,
    serialise,
    unchanged,
)
from project_service.models import (
    ConceiveRevisionRow,
    ConceiveRow,
    ProjectMaterialRow,
    ProjectRow,
)
from project_service.projects import get as get_project

FILE_REF_KINDS = frozenset({"folder", "file"})


class ConceiveReferenceError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ConceiveRevisionNotFoundError(RuntimeError):
    def __init__(self, project_id: str, revision_number: int) -> None:
        super().__init__(f"project {project_id} has no conceive revision {revision_number}")
        self.project_id = project_id
        self.revision_number = revision_number


async def get_or_create(session: AsyncSession, project_id: str) -> ConceiveRow:
    result = await session.execute(select(ConceiveRow).where(ConceiveRow.project_id == project_id))
    row = result.scalars().one_or_none()

    if row is not None:
        return row

    row = ConceiveRow(project_id=project_id)
    session.add(row)
    await session.flush()
    return row


async def find_revision(
    session: AsyncSession, conceive_id: str, revision_number: int
) -> ConceiveRevisionRow | None:
    result = await session.execute(
        select(ConceiveRevisionRow)
        .where(ConceiveRevisionRow.conceive_id == conceive_id)
        .where(ConceiveRevisionRow.revision_number == revision_number)
    )
    return result.scalars().one_or_none()


async def list_revisions(session: AsyncSession, project_id: str) -> list[ConceiveRevisionRow]:
    conceive = await get_or_create(session, project_id)
    result = await session.execute(
        select(ConceiveRevisionRow)
        .where(ConceiveRevisionRow.conceive_id == conceive.id)
        .order_by(ConceiveRevisionRow.revision_number.asc())
    )
    return list(result.scalars().all())


async def current(
    session: AsyncSession, project_id: str
) -> tuple[ConceiveRow, ConceiveRevisionRow | None]:
    await get_project(session, project_id)
    conceive = await get_or_create(session, project_id)

    if conceive.current_revision_number == 0:
        return conceive, None

    return conceive, await find_revision(session, conceive.id, conceive.current_revision_number)


async def revision(
    session: AsyncSession, project_id: str, revision_number: int
) -> ConceiveRevisionRow:
    await get_project(session, project_id)
    conceive = await get_or_create(session, project_id)
    row = await find_revision(session, conceive.id, revision_number)

    if row is None:
        raise ConceiveRevisionNotFoundError(project_id, revision_number)

    return row


def resolve_within(material: ProjectMaterialRow, relative: str) -> Path:
    if material.path is None:
        raise ConceiveReferenceError(f"material {material.id} has no stored copy")

    anchor = Path(material.path).parent
    candidate = (anchor / relative).resolve()

    if not candidate.is_relative_to(anchor.resolve()):
        raise ConceiveReferenceError(f"path {relative} escapes its material")

    return candidate


async def assert_materials(
    session: AsyncSession, project_id: str, blocks: list[ConceiveBlock]
) -> None:
    for block in blocks:
        if not isinstance(block, ImageBlock | FileRefBlock):
            continue

        material = await session.get(ProjectMaterialRow, block.material_id)

        if material is None or material.project_id != project_id:
            raise ConceiveReferenceError(f"material {block.material_id} is not in this project")

        if isinstance(block, ImageBlock) and material.kind != "image":
            raise ConceiveReferenceError(f"material {block.material_id} is not an image")

        if isinstance(block, FileRefBlock):
            if material.kind not in FILE_REF_KINDS:
                raise ConceiveReferenceError(
                    f"material {block.material_id} holds no files to reference"
                )

            if not resolve_within(material, block.path).is_file():
                raise ConceiveReferenceError(f"{block.path} is not a file in this material")


async def assert_projects(
    session: AsyncSession, project_id: str, blocks: list[ConceiveBlock]
) -> None:
    for referenced in project_references(blocks):
        if referenced == project_id:
            raise ConceiveReferenceError("a conceive cannot reference its own project")

        if await session.get(ProjectRow, referenced) is None:
            raise ConceiveReferenceError(f"project {referenced} does not exist")


async def save(
    session: AsyncSession, project_id: str, raw: list[dict[str, Any]]
) -> tuple[ConceiveRow, ConceiveRevisionRow]:
    await get_project(session, project_id)
    blocks = parse_blocks(raw)

    await assert_materials(session, project_id, blocks)
    await assert_projects(session, project_id, blocks)

    conceive = await get_or_create(session, project_id)
    latest = (
        await find_revision(session, conceive.id, conceive.current_revision_number)
        if conceive.current_revision_number
        else None
    )

    if latest is not None and unchanged(latest.blocks, blocks):
        return conceive, latest

    conceive.current_revision_number += 1
    row = ConceiveRevisionRow(
        conceive_id=conceive.id,
        revision_number=conceive.current_revision_number,
        blocks=serialise(blocks),
    )
    session.add(row)

    events.record(
        session,
        project_id,
        "conceive.saved",
        reason=f"revision {conceive.current_revision_number}",
    )

    await session.commit()
    await session.refresh(row)
    await session.refresh(conceive)
    return conceive, row
