from __future__ import annotations

import asyncio
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import events
from project_service.database import data_dir
from project_service.ingest import ingest
from project_service.models import ProjectMaterialRow, UploadScanRow
from project_service.projects import get as get_project
from project_service.scan import ScanResult, scan_directory

SCANNED_KINDS = frozenset({"folder", "file", "image"})


class MaterialNotFoundError(RuntimeError):
    def __init__(self, material_id: str) -> None:
        super().__init__(f"material {material_id} does not exist")
        self.material_id = material_id


class ScanNotFoundError(RuntimeError):
    def __init__(self, material_id: str) -> None:
        super().__init__(f"material {material_id} carries no scan")
        self.material_id = material_id


class MaterialSourceRequiredError(RuntimeError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"material kind {kind} requires source_path")
        self.kind = kind


class MaterialUrlRequiredError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("material kind link requires url")


def material_root(project_id: str, material_id: str) -> Path:
    return data_dir() / "materials" / project_id / material_id


async def list_materials(session: AsyncSession, project_id: str) -> list[ProjectMaterialRow]:
    result = await session.execute(
        select(ProjectMaterialRow)
        .where(ProjectMaterialRow.project_id == project_id)
        .order_by(ProjectMaterialRow.created_at.asc())
    )
    return list(result.scalars().all())


async def get_material(session: AsyncSession, material_id: str) -> ProjectMaterialRow:
    row = await session.get(ProjectMaterialRow, material_id)

    if row is None:
        raise MaterialNotFoundError(material_id)

    return row


async def find_scan(session: AsyncSession, material_id: str) -> UploadScanRow | None:
    result = await session.execute(
        select(UploadScanRow).where(UploadScanRow.material_id == material_id)
    )
    return result.scalars().one_or_none()


async def get_scan(session: AsyncSession, material_id: str) -> UploadScanRow:
    await get_material(session, material_id)
    row = await find_scan(session, material_id)

    if row is None:
        raise ScanNotFoundError(material_id)

    return row


def apply_scan(
    row: UploadScanRow, result: ScanResult, pruned: list[str] | None = None
) -> UploadScanRow:
    row.total_files = result.total_files
    row.total_size_bytes = result.total_size_bytes
    row.file_tree = result.file_tree
    row.languages = [asdict(item) for item in result.languages]
    row.dependency_manifests = [asdict(item) for item in result.dependency_manifests]
    row.entry_points = result.entry_points
    row.secret_findings = [asdict(item) for item in result.secret_findings]
    row.skipped_directories = sorted(set(result.skipped_directories) | set(pruned or []))
    row.truncated = result.truncated
    return row


async def create_link(
    session: AsyncSession, project_id: str, fields: dict[str, Any]
) -> ProjectMaterialRow:
    url = fields.get("url")

    if not url:
        raise MaterialUrlRequiredError

    row = ProjectMaterialRow(
        project_id=project_id,
        kind="link",
        url=str(url),
        caption=fields.get("caption"),
        note=fields.get("note"),
    )
    session.add(row)
    await session.flush()

    events.record(session, project_id, "material.added", material_id=row.id, reason="link")
    await session.commit()
    await session.refresh(row)
    return row


async def create_material(
    session: AsyncSession, project_id: str, fields: dict[str, Any]
) -> ProjectMaterialRow:
    await get_project(session, project_id)
    kind = str(fields["kind"])

    if kind == "link":
        return await create_link(session, project_id, fields)

    source = fields.get("source_path")

    if not source:
        raise MaterialSourceRequiredError(kind)

    row = ProjectMaterialRow(
        project_id=project_id,
        kind=kind,
        caption=fields.get("caption"),
        note=fields.get("note"),
    )
    session.add(row)
    await session.flush()

    destination = material_root(project_id, row.id)

    try:
        payload = await asyncio.to_thread(ingest, Path(str(source)), destination, kind)
        result = await asyncio.to_thread(scan_directory, destination)
    except Exception:
        await session.rollback()
        shutil.rmtree(destination, ignore_errors=True)
        raise

    row.path = str(destination / payload.stored_name)
    row.size_bytes = payload.size_bytes
    row.content_hash = payload.content_hash

    session.add(
        apply_scan(
            UploadScanRow(project_id=project_id, material_id=row.id),
            result,
            payload.skipped_directories,
        )
    )
    events.record(session, project_id, "material.added", material_id=row.id, reason=kind)

    await session.commit()
    await session.refresh(row)
    return row


async def rescan(session: AsyncSession, material_id: str) -> UploadScanRow:
    material = await get_material(session, material_id)

    if material.kind not in SCANNED_KINDS:
        raise ScanNotFoundError(material_id)

    destination = material_root(material.project_id, material.id)
    result = await asyncio.to_thread(scan_directory, destination)
    row = await find_scan(session, material_id)

    if row is None:
        row = UploadScanRow(project_id=material.project_id, material_id=material_id)
        session.add(row)

    apply_scan(row, result, list(row.skipped_directories or []))
    events.record(
        session,
        material.project_id,
        "material.rescanned",
        material_id=material_id,
        reason=material.kind,
    )

    await session.commit()
    await session.refresh(row)
    return row


async def delete_material(session: AsyncSession, material_id: str) -> None:
    material = await get_material(session, material_id)
    project_id = material.project_id
    scan = await find_scan(session, material_id)

    if scan is not None:
        await session.delete(scan)

    await session.delete(material)
    events.record(
        session,
        project_id,
        "material.removed",
        material_id=material_id,
        reason=material.kind,
    )

    await session.commit()
    shutil.rmtree(material_root(project_id, material_id), ignore_errors=True)
