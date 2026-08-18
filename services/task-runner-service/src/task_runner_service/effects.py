from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from task_runner_service.sandbox import FileEffect

HASH_CHUNK_BYTES = 1 << 20

MAX_REPORTED_FILES = 200


@dataclass(frozen=True)
class Snapshot:
    entries: dict[str, tuple[int, int]]


@dataclass(frozen=True)
class FilesystemDelta:
    written: list[FileEffect]
    deleted: list[str]
    written_total: int
    deleted_total: int
    truncated: bool


def walk(root: str) -> dict[str, tuple[int, int]]:
    collected: dict[str, tuple[int, int]] = {}
    base = Path(root)

    if not base.is_dir():
        return collected

    for directory, _, names in os.walk(base):
        for name in names:
            path = Path(directory) / name

            try:
                info = path.lstat()
            except OSError:
                continue

            if not stat.S_ISREG(info.st_mode):
                continue

            collected[str(path)] = (info.st_size, info.st_mtime_ns)

    return collected


def snapshot(roots: list[str]) -> Snapshot:
    entries: dict[str, tuple[int, int]] = {}

    for root in roots:
        entries.update(walk(root))

    return Snapshot(entries=entries)


def digest(path: str) -> str:
    hasher = hashlib.sha256()

    with Path(path).open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_BYTES):
            hasher.update(chunk)

    return hasher.hexdigest()


def effect(path: str, size: int) -> FileEffect | None:
    try:
        return FileEffect(path=path, sha256=digest(path), size_bytes=size)
    except OSError:
        return None


def changed(before: Snapshot, after: Snapshot) -> list[tuple[str, int]]:
    return [
        (path, fingerprint[0])
        for path, fingerprint in sorted(after.entries.items())
        if before.entries.get(path) != fingerprint
    ]


def compare(before: Snapshot, after: Snapshot) -> FilesystemDelta:
    modified = changed(before, after)
    removed = sorted(path for path in before.entries if path not in after.entries)

    written: list[FileEffect] = []

    for path, size in modified[:MAX_REPORTED_FILES]:
        produced = effect(path, size)

        if produced is not None:
            written.append(produced)

    return FilesystemDelta(
        written=written,
        deleted=removed[:MAX_REPORTED_FILES],
        written_total=len(modified),
        deleted_total=len(removed),
        truncated=len(modified) > MAX_REPORTED_FILES or len(removed) > MAX_REPORTED_FILES,
    )


def observe(before: Snapshot, roots: list[str]) -> FilesystemDelta:
    return compare(before, snapshot(roots))
