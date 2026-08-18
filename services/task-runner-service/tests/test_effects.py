from __future__ import annotations

import os
from pathlib import Path

from task_runner_service.effects import compare, digest, observe, snapshot

HELLO_SHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    return path


def bump(path: Path) -> None:
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))


def test_a_missing_root_snapshots_as_empty(tmp_path: Path) -> None:
    assert snapshot([str(tmp_path / "absent")]).entries == {}


def test_an_empty_directory_snapshots_as_empty(tmp_path: Path) -> None:
    assert snapshot([str(tmp_path)]).entries == {}


def test_a_snapshot_reaches_nested_directories(tmp_path: Path) -> None:
    write(tmp_path / "src" / "deep" / "a.txt", b"a")

    assert len(snapshot([str(tmp_path)]).entries) == 1


def test_a_snapshot_spans_several_roots(tmp_path: Path) -> None:
    write(tmp_path / "one" / "a.txt", b"a")
    write(tmp_path / "two" / "b.txt", b"b")

    roots = [str(tmp_path / "one"), str(tmp_path / "two")]

    assert len(snapshot(roots).entries) == 2


def test_digest_matches_a_known_hash(tmp_path: Path) -> None:
    target = write(tmp_path / "hello.txt", b"hello")

    assert digest(str(target)) == HELLO_SHA256


def test_a_new_file_is_reported_as_written(tmp_path: Path) -> None:
    before = snapshot([str(tmp_path)])
    write(tmp_path / "out.txt", b"hello")

    delta = observe(before, [str(tmp_path)])

    assert [entry.path for entry in delta.written] == [str(tmp_path / "out.txt")]
    assert delta.written[0].sha256 == HELLO_SHA256
    assert delta.written[0].size_bytes == 5
    assert delta.deleted == []


def test_an_untouched_file_is_not_reported(tmp_path: Path) -> None:
    write(tmp_path / "stable.txt", b"stable")
    before = snapshot([str(tmp_path)])

    delta = observe(before, [str(tmp_path)])

    assert delta.written == []
    assert delta.deleted == []


def test_a_file_that_changed_size_is_reported(tmp_path: Path) -> None:
    target = write(tmp_path / "grow.txt", b"a")
    before = snapshot([str(tmp_path)])
    write(target, b"aaaa")

    delta = observe(before, [str(tmp_path)])

    assert [entry.size_bytes for entry in delta.written] == [4]


def test_a_rewrite_of_the_same_length_is_reported_when_the_timestamp_moves(tmp_path: Path) -> None:
    target = write(tmp_path / "same.txt", b"aaaa")
    before = snapshot([str(tmp_path)])
    target.write_bytes(b"bbbb")
    bump(target)

    delta = observe(before, [str(tmp_path)])

    assert len(delta.written) == 1


def test_a_deleted_file_is_reported_and_not_hashed(tmp_path: Path) -> None:
    target = write(tmp_path / "gone.txt", b"gone")
    before = snapshot([str(tmp_path)])
    target.unlink()

    delta = observe(before, [str(tmp_path)])

    assert delta.written == []
    assert delta.deleted == [str(target)]


def test_writes_and_deletes_are_reported_together(tmp_path: Path) -> None:
    removed = write(tmp_path / "old.txt", b"old")
    before = snapshot([str(tmp_path)])
    removed.unlink()
    write(tmp_path / "new.txt", b"new")

    delta = observe(before, [str(tmp_path)])

    assert [entry.path for entry in delta.written] == [str(tmp_path / "new.txt")]
    assert delta.deleted == [str(removed)]


def test_written_files_are_reported_in_a_stable_order(tmp_path: Path) -> None:
    before = snapshot([str(tmp_path)])

    for name in ("c.txt", "a.txt", "b.txt"):
        write(tmp_path / name, b"x")

    delta = observe(before, [str(tmp_path)])

    assert [Path(entry.path).name for entry in delta.written] == ["a.txt", "b.txt", "c.txt"]


def test_a_file_removed_between_snapshot_and_hash_is_skipped(tmp_path: Path) -> None:
    write(tmp_path / "racing.txt", b"racing")
    after = snapshot([str(tmp_path)])
    (tmp_path / "racing.txt").unlink()

    delta = compare(snapshot([str(tmp_path)]), after)

    assert delta.written == []
