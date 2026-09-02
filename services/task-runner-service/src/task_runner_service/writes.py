from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from task_runner_service.effects import digest
from task_runner_service.sandbox import FileEffect, Mount
from task_runner_service.scope import contained, root_segments, unresolvable

MAX_CONTENT_BYTES = 1 << 21

TEMPORARY_SUFFIX = ".bison-partial"


class WriteRefusedError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class WriteResult:
    step_id: str
    path: str
    files_written: list[FileEffect]
    error_message: str | None
    started_at: datetime
    ended_at: datetime


def writable_roots(mounts: list[Mount]) -> list[list[str]]:
    return [root_segments(mount.path) for mount in mounts if mount.writable]


def permitted(path: str, mounts: list[Mount]) -> bool:
    return any(contained(path, root) for root in writable_roots(mounts))


def encoded(content: str) -> bytes:
    payload = content.encode("utf-8")

    if len(payload) > MAX_CONTENT_BYTES:
        raise WriteRefusedError(
            f"the file is {len(payload)} bytes, above the {MAX_CONTENT_BYTES} byte limit"
        )

    return payload


def verified(path: str, mounts: list[Mount]) -> Path:
    if unresolvable(path):
        raise WriteRefusedError(f"the path '{path}' is not one this machine can resolve")

    if not Path(path).is_absolute():
        raise WriteRefusedError(f"the path '{path}' must be absolute")

    if not permitted(path, mounts):
        raise WriteRefusedError(f"the path '{path}' lies outside every writable mount")

    return Path(path)


def commit(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    staging = target.with_name(target.name + TEMPORARY_SUFFIX)

    try:
        with staging.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(staging, target)
    finally:
        if staging.exists():
            staging.unlink(missing_ok=True)


def perform(step_id: str, path: str, content: str, mounts: list[Mount]) -> WriteResult:
    started_at = datetime.now(UTC)
    target = verified(path, mounts)
    payload = encoded(content)

    try:
        commit(target, payload)
    except OSError as error:
        return WriteResult(
            step_id=step_id,
            path=str(target),
            files_written=[],
            error_message=f"the file could not be written: {error.strerror or error}",
            started_at=started_at,
            ended_at=datetime.now(UTC),
        )

    return WriteResult(
        step_id=step_id,
        path=str(target),
        files_written=[
            FileEffect(path=str(target), sha256=digest(str(target)), size_bytes=len(payload))
        ],
        error_message=None,
        started_at=started_at,
        ended_at=datetime.now(UTC),
    )
