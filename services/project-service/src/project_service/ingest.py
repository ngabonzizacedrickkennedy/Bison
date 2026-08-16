from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import puremagic
from PIL import Image, UnidentifiedImageError

from project_service.scan import IGNORED_DIRECTORIES

HASH_CHUNK_BYTES = 1_048_576
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff"})


class MaterialSourceNotFoundError(RuntimeError):
    def __init__(self, source: Path) -> None:
        super().__init__(f"no file or directory at {source}")
        self.source = source


class MaterialSourceInvalidError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class IngestedPayload:
    root: Path
    stored_name: str
    size_bytes: int
    content_hash: str
    detected_type: str | None
    skipped_directories: list[str]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_BYTES):
            digest.update(chunk)

    return digest.hexdigest()


def hash_directory(root: Path) -> str:
    digest = hashlib.sha256()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(hash_file(path).encode("ascii"))

    return digest.hexdigest()


def directory_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def pruner(anchor: Path, collected: set[str]) -> Callable[[str, list[str]], set[str]]:
    def prune(directory: str, names: list[str]) -> set[str]:
        base = Path(directory)
        dropped = {name for name in names if name in IGNORED_DIRECTORIES and (base / name).is_dir()}
        collected.update((base / name).relative_to(anchor).as_posix() for name in dropped)
        return dropped

    return prune


def detected_type(path: Path) -> str | None:
    try:
        matches = puremagic.magic_file(str(path))
    except (OSError, ValueError):
        return None

    return matches[0].mime_type if matches else None


def assert_real_image(path: Path) -> None:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise MaterialSourceInvalidError(f"{path.name} does not carry an image extension")

    try:
        with Image.open(path) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as error:
        raise MaterialSourceInvalidError(f"{path.name} is not a readable image") from error


def assert_disjoint(source: Path, destination: Path) -> None:
    if source == destination or destination.is_relative_to(source):
        raise MaterialSourceInvalidError("destination lies inside the source directory")


def ingest(source: Path, destination: Path, kind: str) -> IngestedPayload:
    resolved = source.expanduser().resolve()

    if not resolved.exists():
        raise MaterialSourceNotFoundError(resolved)

    if kind == "folder" and not resolved.is_dir():
        raise MaterialSourceInvalidError(f"{resolved} is not a directory")

    if kind in {"file", "image"} and not resolved.is_file():
        raise MaterialSourceInvalidError(f"{resolved} is not a file")

    if kind == "image":
        assert_real_image(resolved)

    assert_disjoint(resolved, destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / resolved.name

    if resolved.is_dir():
        collected: set[str] = set()
        shutil.copytree(
            resolved, target, ignore=pruner(resolved.parent, collected), dirs_exist_ok=True
        )
        return IngestedPayload(
            root=destination,
            stored_name=resolved.name,
            size_bytes=directory_size(target),
            content_hash=hash_directory(target),
            detected_type=None,
            skipped_directories=sorted(collected),
        )

    shutil.copy2(resolved, target)
    return IngestedPayload(
        root=destination,
        stored_name=resolved.name,
        size_bytes=target.stat().st_size,
        content_hash=hash_file(target),
        detected_type=detected_type(target),
        skipped_directories=[],
    )
