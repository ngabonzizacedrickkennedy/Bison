from __future__ import annotations

from typing import Any

import pytest

from mediator_service.resolve import (
    PYTHON,
    RUNNABLE_TYPES,
    Invocation,
    UnrunnableActionError,
    invocation,
    runnable,
)

SCRIPT = "C:\\scope\\count_files.py"


def write_file(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"type": "write_file", "path": SCRIPT, "content": "print(1)\n"}
    base.update(overrides)

    return base


def run_script(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "run_python_script",
        "script_path": SCRIPT,
        "arguments": ["--verbose"],
    }
    base.update(overrides)

    return base


def run_module(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "run_python_module",
        "module": "pytest",
        "arguments": ["-q", "tests"],
    }
    base.update(overrides)

    return base


def install(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"type": "install_python_packages", "packages": ["fastapi"]}
    base.update(overrides)

    return base


def test_a_script_runs_under_the_interpreter_the_runner_chooses() -> None:
    assert invocation(run_script()) == Invocation(PYTHON, (SCRIPT, "--verbose"))


def test_a_module_runs_through_dash_m() -> None:
    assert invocation(run_module()) == Invocation(PYTHON, ("-m", "pytest", "-q", "tests"))


def test_an_install_never_calls_the_pip_shim() -> None:
    resolved = invocation(install(packages=["fastapi", "uvicorn"]))

    assert resolved == Invocation(PYTHON, ("-m", "pip", "install", "fastapi", "uvicorn"))
    assert "pip.exe" not in resolved.program


def test_every_runnable_action_asks_for_the_bare_interpreter_name() -> None:
    for entry in (run_script(), run_module(), install()):
        assert invocation(entry).program == PYTHON


def test_the_program_is_never_a_path_because_the_runner_substitutes_it() -> None:
    for entry in (run_script(), run_module(), install()):
        program = invocation(entry).program

        assert "\\" not in program
        assert "/" not in program
        assert not program.lower().endswith(".exe")


def test_a_script_with_no_arguments_runs_alone() -> None:
    assert invocation(run_script(arguments=[])).arguments == (SCRIPT,)


def test_absent_arguments_are_read_as_none_given() -> None:
    entry = run_module()
    del entry["arguments"]

    assert invocation(entry).arguments == ("-m", "pytest")


def test_arguments_keep_their_order() -> None:
    resolved = invocation(run_script(arguments=["first", "second", "third"]))

    assert resolved.arguments == (SCRIPT, "first", "second", "third")


def test_an_empty_argument_survives_because_a_program_may_want_one() -> None:
    assert invocation(run_script(arguments=["--name", ""])).arguments == (SCRIPT, "--name", "")


def test_a_write_is_not_a_program_and_says_so() -> None:
    with pytest.raises(UnrunnableActionError, match="carried out by the runner directly"):
        invocation(write_file())


def test_a_step_with_no_action_cannot_be_run() -> None:
    with pytest.raises(UnrunnableActionError, match="carries no action"):
        invocation(None)


def test_an_action_without_a_type_cannot_be_run() -> None:
    with pytest.raises(UnrunnableActionError, match="does not say what kind"):
        invocation({"script_path": SCRIPT})


def test_an_unknown_action_type_names_the_ones_that_run() -> None:
    with pytest.raises(UnrunnableActionError) as raised:
        invocation({"type": "run_shell", "command": "del *.*"})

    for name in RUNNABLE_TYPES:
        assert name in raised.value.detail


def test_a_missing_script_path_names_the_field() -> None:
    entry = run_script()
    del entry["script_path"]

    with pytest.raises(UnrunnableActionError, match="needs a script_path"):
        invocation(entry)


def test_a_missing_module_names_the_field() -> None:
    entry = run_module()
    del entry["module"]

    with pytest.raises(UnrunnableActionError, match="needs a module"):
        invocation(entry)


def test_an_install_with_nothing_to_install_is_refused() -> None:
    with pytest.raises(UnrunnableActionError, match="at least one package"):
        invocation(install(packages=[]))


def test_an_argument_that_is_not_a_string_is_refused_rather_than_dropped() -> None:
    with pytest.raises(UnrunnableActionError, match="must be a string"):
        invocation(run_module(arguments=["-q", 7]))


def test_arguments_that_are_not_an_array_are_refused() -> None:
    with pytest.raises(UnrunnableActionError, match="array of strings"):
        invocation(run_module(arguments="-q tests"))


def test_a_write_is_not_reported_as_runnable() -> None:
    assert not runnable(write_file())


def test_every_other_action_is_reported_as_runnable() -> None:
    for entry in (run_script(), run_module(), install()):
        assert runnable(entry)


def test_nothing_at_all_is_not_runnable() -> None:
    assert not runnable(None)
    assert not runnable({})
    assert not runnable({"type": "run_shell"})
