from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from task_runner_service.sandbox import Mount
from task_runner_service.writes import (
    MAX_CONTENT_BYTES,
    TEMPORARY_SUFFIX,
    WriteRefusedError,
    perform,
)

SOURCE = "import os\n\n\nprint(len(os.listdir('.')))\n"


@pytest.fixture
def scope(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "workspace"
    root.mkdir()

    yield root


def mounts_for(root: Path) -> list[Mount]:
    return [Mount(path=str(root), writable=True)]


def written(root: Path, name: str = "main.py", content: str = SOURCE) -> Path:
    target = root / name
    perform("s-1", str(target), content, mounts_for(root))

    return target


def test_a_file_is_created_with_the_content_it_was_given(scope: Path) -> None:
    target = written(scope)

    assert target.read_bytes().decode("utf-8") == SOURCE


def test_newlines_are_never_translated_to_windows_endings(scope: Path) -> None:
    raw = written(scope).read_bytes()

    assert b"\r\n" not in raw
    assert raw.count(b"\n") == SOURCE.count("\n")


def test_carriage_returns_the_author_asked_for_are_kept(scope: Path) -> None:
    target = written(scope, content="first\r\nsecond\r\n")

    assert target.read_bytes() == b"first\r\nsecond\r\n"


def test_the_reported_hash_matches_the_bytes_on_disk(scope: Path) -> None:
    target = scope / "main.py"
    result = perform("s-1", str(target), SOURCE, mounts_for(scope))
    expected = hashlib.sha256(target.read_bytes()).hexdigest()

    assert result.files_written[0].sha256 == expected


def test_the_reported_size_matches_the_bytes_on_disk(scope: Path) -> None:
    target = scope / "main.py"
    result = perform("s-1", str(target), SOURCE, mounts_for(scope))

    assert result.files_written[0].size_bytes == target.stat().st_size


def test_a_written_file_is_reported_exactly_once(scope: Path) -> None:
    result = perform("s-1", str(scope / "main.py"), SOURCE, mounts_for(scope))

    assert len(result.files_written) == 1
    assert result.error_message is None


def test_an_empty_file_is_legitimate(scope: Path) -> None:
    target = written(scope, name="__init__.py", content="")

    assert target.is_file()
    assert target.read_bytes() == b""


def test_text_outside_ascii_survives_as_utf_eight(scope: Path) -> None:
    body = f"# réconciliation{chr(0x2011)}totale\nprint('café')\n"
    target = written(scope, content=body)

    assert target.read_bytes().decode("utf-8") == body


def test_a_missing_parent_directory_is_created(scope: Path) -> None:
    target = written(scope, name="src/app/main.py")

    assert target.is_file()


def test_writing_over_a_file_replaces_it_entirely(scope: Path) -> None:
    target = written(scope, content="the first version, which is longer\n")
    written(scope, content="second\n")

    assert target.read_bytes() == b"second\n"


def test_no_partial_file_is_left_behind(scope: Path) -> None:
    written(scope)
    leftovers = list(scope.rglob(f"*{TEMPORARY_SUFFIX}"))

    assert leftovers == []


def test_a_write_outside_the_scope_is_refused(scope: Path, tmp_path: Path) -> None:
    with pytest.raises(WriteRefusedError, match="outside every writable mount"):
        perform("s-1", str(tmp_path / "escape.txt"), SOURCE, mounts_for(scope))


def test_an_escape_through_a_parent_reference_is_refused(scope: Path) -> None:
    with pytest.raises(WriteRefusedError, match="outside every writable mount"):
        perform("s-1", str(scope / ".." / "escape.txt"), SOURCE, mounts_for(scope))


def test_a_read_only_mount_is_not_writable(scope: Path) -> None:
    with pytest.raises(WriteRefusedError, match="outside every writable mount"):
        perform("s-1", str(scope / "main.py"), SOURCE, [Mount(path=str(scope), writable=False)])


def test_a_relative_path_is_refused(scope: Path) -> None:
    with pytest.raises(WriteRefusedError, match="must be absolute"):
        perform("s-1", "main.py", SOURCE, mounts_for(scope))


def test_a_path_holding_a_variable_is_refused(scope: Path) -> None:
    with pytest.raises(WriteRefusedError, match="can resolve"):
        perform("s-1", r"%TEMP%\escape.txt", SOURCE, mounts_for(scope))


def test_a_refused_write_leaves_nothing_on_disk(scope: Path, tmp_path: Path) -> None:
    escape = tmp_path / "escape.txt"

    with pytest.raises(WriteRefusedError):
        perform("s-1", str(escape), SOURCE, mounts_for(scope))

    assert not escape.exists()


def test_a_file_beyond_the_size_limit_is_refused(scope: Path) -> None:
    with pytest.raises(WriteRefusedError, match="byte limit"):
        perform("s-1", str(scope / "big.py"), "x" * (MAX_CONTENT_BYTES + 1), mounts_for(scope))


def test_the_limit_counts_bytes_rather_than_characters(scope: Path) -> None:
    oversized = "é" * ((MAX_CONTENT_BYTES // 2) + 1)

    with pytest.raises(WriteRefusedError, match="byte limit"):
        perform("s-1", str(scope / "big.py"), oversized, mounts_for(scope))


def test_the_step_it_was_asked_for_is_the_step_it_reports(scope: Path) -> None:
    result = perform("s-42", str(scope / "main.py"), SOURCE, mounts_for(scope))

    assert result.step_id == "s-42"


def test_a_write_records_when_it_started_and_ended(scope: Path) -> None:
    result = perform("s-1", str(scope / "main.py"), SOURCE, mounts_for(scope))

    assert result.ended_at >= result.started_at
    assert result.started_at.tzinfo is not None
