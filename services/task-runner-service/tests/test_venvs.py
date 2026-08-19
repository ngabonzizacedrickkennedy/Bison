from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from task_runner_service import venvs
from task_runner_service.venvs import EnvironmentUnavailableError


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path.resolve()


def test_a_key_becomes_a_readable_directory_name() -> None:
    assert venvs.slug("task-42").startswith("task-42-")


def test_unsafe_characters_are_stripped_from_the_name() -> None:
    assert "/" not in venvs.slug("task/../escape")
    assert "." not in venvs.slug("task/../escape")


def test_two_keys_never_share_a_directory() -> None:
    assert venvs.slug("task-a") != venvs.slug("task-b")


def test_keys_that_clean_to_the_same_text_stay_distinct() -> None:
    assert venvs.slug("task/one") != venvs.slug("task:one")


def test_an_empty_key_still_produces_a_name() -> None:
    assert venvs.slug("") != ""


def test_a_missing_environment_is_incomplete(root: Path) -> None:
    assert not venvs.complete(venvs.home(root, "absent"))


async def test_an_environment_is_created_on_demand(root: Path) -> None:
    venv = await venvs.ensure(root, "task-1")

    assert venvs.complete(venv)
    assert venvs.interpreter(venv).is_file()


async def test_the_same_key_reuses_the_same_environment(root: Path) -> None:
    first = await venvs.ensure(root, "task-1")
    marker = first / "installed.txt"
    marker.write_text("present", newline="\n")

    second = await venvs.ensure(root, "task-1")

    assert first == second
    assert marker.is_file()


async def test_different_keys_get_separate_environments(root: Path) -> None:
    first = await venvs.ensure(root, "task-1")
    second = await venvs.ensure(root, "task-2")

    assert first != second
    assert venvs.complete(first)
    assert venvs.complete(second)


async def test_concurrent_requests_build_one_environment(root: Path) -> None:
    results = await asyncio.gather(*(venvs.ensure(root, "task-1") for _ in range(4)))

    assert len(set(results)) == 1
    assert venvs.complete(results[0])


async def test_the_environment_interpreter_is_not_the_machine_interpreter(root: Path) -> None:
    venv = await venvs.ensure(root, "task-1")

    assert venvs.interpreter(venv) != Path(sys.executable)


def test_a_bare_python_program_is_redirected(root: Path) -> None:
    venv = venvs.home(root, "task-1")

    assert venvs.resolve("python", venv) == str(venvs.interpreter(venv))


def test_an_absolute_machine_python_is_redirected(root: Path) -> None:
    venv = venvs.home(root, "task-1")

    assert venvs.resolve(sys.executable, venv) == str(venvs.interpreter(venv))


def test_a_program_that_is_not_python_is_left_alone(root: Path) -> None:
    venv = venvs.home(root, "task-1")

    assert venvs.resolve("git", venv) == "git"


def test_the_overlay_points_at_the_environment(root: Path) -> None:
    venv = venvs.home(root, "task-1")
    merged = venvs.overlay({"PATH": "C:\\existing"}, venv)

    assert merged["VIRTUAL_ENV"] == str(venv)
    assert merged["PATH"].startswith(str(venv / venvs.BIN_DIRECTORY))
    assert merged["PATH"].endswith("C:\\existing")


def test_the_overlay_survives_an_empty_path(root: Path) -> None:
    venv = venvs.home(root, "task-1")
    merged = venvs.overlay({}, venv)

    assert merged["PATH"] == str(venv / venvs.BIN_DIRECTORY)


def test_the_overlay_blocks_user_site_packages(root: Path) -> None:
    merged = venvs.overlay({}, venvs.home(root, "task-1"))

    assert merged["PYTHONNOUSERSITE"] == "1"


def test_the_overlay_removes_a_python_home(root: Path) -> None:
    merged = venvs.overlay({"PYTHONHOME": "C:\\Python312"}, venvs.home(root, "task-1"))

    assert "PYTHONHOME" not in merged


def test_the_overlay_does_not_mutate_what_it_was_given(root: Path) -> None:
    original = {"PATH": "C:\\existing"}

    venvs.overlay(original, venvs.home(root, "task-1"))

    assert original == {"PATH": "C:\\existing"}


async def test_a_missing_uv_is_reported_clearly(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def absent(_name: str) -> str | None:
        return None

    monkeypatch.setattr("task_runner_service.venvs.shutil.which", absent)

    with pytest.raises(EnvironmentUnavailableError, match="uv is not on PATH"):
        await venvs.ensure(root, "task-1")


async def test_an_environment_built_here_actually_runs(root: Path) -> None:
    venv = await venvs.ensure(root, "task-1")

    process = await asyncio.create_subprocess_exec(
        str(venvs.interpreter(venv)),
        "-c",
        "import sys;print(sys.prefix)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={key: os.environ[key] for key in ("SYSTEMROOT", "PATH") if key in os.environ},
    )
    out, _err = await process.communicate()

    assert Path(out.decode().strip()) == venv
    assert process.returncode == 0
