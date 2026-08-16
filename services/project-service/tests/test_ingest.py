from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from project_service.ingest import (
    MaterialSourceInvalidError,
    MaterialSourceNotFoundError,
    ingest,
)


def build(root: Path, files: dict[str, str]) -> None:
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")


def chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def write_png(path: Path) -> None:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def test_folder_is_copied_with_structure_preserved(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"src/app.py": "x = 1\n", "README.md": "# r\n"})

    payload = ingest(source, tmp_path / "store", "folder")
    stored = tmp_path / "store" / "repo"

    assert payload.stored_name == "repo"
    assert (stored / "src" / "app.py").read_text() == "x = 1\n"
    assert (stored / "README.md").exists()


def test_ignored_directories_are_not_copied(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"src/app.py": "x = 1\n", "node_modules/pkg/index.js": "junk\n"})

    payload = ingest(source, tmp_path / "store", "folder")

    assert not (tmp_path / "store" / "repo" / "node_modules").exists()
    assert payload.skipped_directories == ["repo/node_modules"]


def test_nested_pruned_directories_are_reported_with_their_path(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"api/dist/a.js": "j\n", "web/node_modules/b.js": "j\n", "keep/c.py": "x = 1\n"})

    payload = ingest(source, tmp_path / "store", "folder")

    assert payload.skipped_directories == ["repo/api/dist", "repo/web/node_modules"]


def test_size_excludes_pruned_directories(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"a.py": "x = 1\n", "dist/big.js": "j" * 5000})

    assert ingest(source, tmp_path / "store", "folder").size_bytes == 6


def test_content_hash_is_stable_across_copies(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"a.py": "x = 1\n", "b/c.py": "y = 2\n"})

    first = ingest(source, tmp_path / "one", "folder")
    second = ingest(source, tmp_path / "two", "folder")

    assert first.content_hash == second.content_hash


def test_content_hash_changes_when_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"a.py": "x = 1\n"})
    before = ingest(source, tmp_path / "one", "folder")

    build(source, {"a.py": "x = 2\n"})
    after = ingest(source, tmp_path / "two", "folder")

    assert before.content_hash != after.content_hash


def test_content_hash_changes_when_a_file_is_renamed(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"a.py": "x = 1\n"})
    before = ingest(source, tmp_path / "one", "folder")

    (source / "a.py").rename(source / "b.py")
    after = ingest(source, tmp_path / "two", "folder")

    assert before.content_hash != after.content_hash


def test_single_file_is_ingested_with_detected_type(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("hello\n", encoding="utf-8", newline="\n")

    payload = ingest(source, tmp_path / "store", "file")

    assert payload.stored_name == "notes.txt"
    assert payload.size_bytes == 6
    assert (tmp_path / "store" / "notes.txt").exists()


def test_real_image_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "logo.png"
    write_png(source)

    payload = ingest(source, tmp_path / "store", "image")

    assert payload.detected_type == "image/png"


def test_text_renamed_as_png_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "fake.png"
    source.write_text("not an image at all\n", encoding="utf-8", newline="\n")

    with pytest.raises(MaterialSourceInvalidError):
        ingest(source, tmp_path / "store", "image")


def test_image_without_image_extension_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "logo.bin"
    write_png(source)

    with pytest.raises(MaterialSourceInvalidError):
        ingest(source, tmp_path / "store", "image")


def test_missing_source_is_reported(tmp_path: Path) -> None:
    with pytest.raises(MaterialSourceNotFoundError):
        ingest(tmp_path / "absent", tmp_path / "store", "folder")


def test_folder_kind_rejects_a_file(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("x\n", encoding="utf-8", newline="\n")

    with pytest.raises(MaterialSourceInvalidError):
        ingest(source, tmp_path / "store", "folder")


def test_file_kind_rejects_a_directory(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"a.py": "x = 1\n"})

    with pytest.raises(MaterialSourceInvalidError):
        ingest(source, tmp_path / "store", "file")


def test_destination_inside_source_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    build(source, {"a.py": "x = 1\n"})

    with pytest.raises(MaterialSourceInvalidError):
        ingest(source, source / "store", "folder")
