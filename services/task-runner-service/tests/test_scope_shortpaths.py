from __future__ import annotations

from pathlib import PureWindowsPath

import pytest

from task_runner_service.scope import contained, home_shorthand, root_segments, unresolvable

SHORT_ROOT = r"C:\Users\CEDRIC~1.NGA\bison-workspace"
LONG_ROOT = r"C:\Users\cedrick.ngabonziza\bison-workspace"


def test_a_short_name_is_a_real_path_not_a_variable() -> None:
    assert not unresolvable(SHORT_ROOT)


def test_a_short_name_root_contains_itself() -> None:
    assert contained(SHORT_ROOT, root_segments(SHORT_ROOT))


def test_a_file_under_a_short_name_root_is_inside_it() -> None:
    assert contained(SHORT_ROOT + r"\src\main.py", root_segments(SHORT_ROOT))


def test_a_short_name_elsewhere_in_the_path_is_allowed() -> None:
    assert contained(LONG_ROOT + r"\PROGRA~1\note.txt", root_segments(LONG_ROOT))


def test_a_tilde_inside_a_file_name_is_allowed() -> None:
    assert contained(LONG_ROOT + r"\draft~1.txt", root_segments(LONG_ROOT))


def test_a_short_name_outside_the_root_is_still_outside() -> None:
    assert not contained(r"C:\Users\CEDRIC~1.NGA\Desktop\notes.txt", root_segments(SHORT_ROOT))


@pytest.mark.parametrize("path", ["~", r"~\Documents", "~/Documents", r".\~\secrets"])
def test_home_shorthand_is_still_refused(path: str) -> None:
    assert unresolvable(path)
    assert not contained(path, root_segments(LONG_ROOT))


@pytest.mark.parametrize("path", [r"%TEMP%\x.txt", r"$env:USERPROFILE\x.txt"])
def test_a_variable_is_still_refused(path: str) -> None:
    assert unresolvable(path)


def test_only_a_leading_tilde_is_home_shorthand() -> None:
    assert home_shorthand(PureWindowsPath(r"~\Documents"))
    assert not home_shorthand(PureWindowsPath(SHORT_ROOT))
    assert not home_shorthand(PureWindowsPath(r"C:\x\~y\z"))


def test_a_drive_relative_path_is_still_refused() -> None:
    assert unresolvable(r"C:src\main.py")
