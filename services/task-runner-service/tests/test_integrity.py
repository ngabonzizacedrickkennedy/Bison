from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="integrity labels are Windows only")

if TYPE_CHECKING or sys.platform == "win32":
    from task_runner_service import integrity


def test_this_machine_can_lower_a_token() -> None:
    assert integrity.available()


def test_a_restricted_token_reports_low_integrity() -> None:
    token = integrity.restricted_token()

    try:
        assert integrity.token_level(token) == integrity.LOW_INTEGRITY_SID
    finally:
        integrity.close(token)


def test_this_process_is_not_low_integrity() -> None:
    token = integrity.restricted_token()

    try:
        assert integrity.token_level(token) != _own_level()
    finally:
        integrity.close(token)


def _own_level() -> str:
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)

    try:
        return str(integrity.token_level(token))
    finally:
        win32api.CloseHandle(token)


def test_an_unlabelled_directory_reports_no_label(tmp_path: Path) -> None:
    assert integrity.label_of(tmp_path.resolve()) is None


def test_a_labelled_directory_reports_low(tmp_path: Path) -> None:
    scope = tmp_path.resolve()

    integrity.label_low(scope)

    assert integrity.label_of(scope) == integrity.LOW_INTEGRITY_SID


def test_the_label_is_inherited_by_new_children(tmp_path: Path) -> None:
    scope = tmp_path.resolve()

    integrity.label_low(scope)

    child = scope / "child"
    child.mkdir()

    assert integrity.label_of(child) == integrity.LOW_INTEGRITY_SID


def test_a_label_can_be_removed(tmp_path: Path) -> None:
    scope = tmp_path.resolve()

    integrity.label_low(scope)
    integrity.apply_label(scope, None)

    assert integrity.label_of(scope) is None


def test_removing_a_label_leaves_the_directory_usable(tmp_path: Path) -> None:
    scope = tmp_path.resolve()

    integrity.label_low(scope)
    integrity.apply_label(scope, None)

    written = scope / "after.txt"
    written.write_text("restored", newline="\n")

    assert written.read_text() == "restored"


def test_a_prior_label_survives_a_restore(tmp_path: Path) -> None:
    scope = tmp_path.resolve()

    integrity.label_low(scope)
    previous = integrity.label_of(scope)

    integrity.label_low(scope)
    integrity.apply_label(scope, previous)

    assert integrity.label_of(scope) == integrity.LOW_INTEGRITY_SID
