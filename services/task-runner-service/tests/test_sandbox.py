from __future__ import annotations

import pytest

from task_runner_service.sandbox import (
    InvalidSandboxRequestError,
    Limits,
    Mount,
    SandboxRequest,
    assert_valid,
    program_kind,
    writable_mounts,
)

WORKSPACE = r"C:\Users\x\bison\workspaces\task-1"

REFERENCE = r"C:\Users\x\bison\materials"


def limits(**overrides: int) -> Limits:
    declared = {"wall_clock_seconds": 300, "memory_mb": 512, "max_output_bytes": 1_048_576}
    declared.update(overrides)

    return Limits(**declared)


def request(**overrides: object) -> SandboxRequest:
    declared: dict[str, object] = {
        "step_id": "step-1",
        "program": "python",
        "arguments": ["-c", "print(1)"],
        "working_directory": WORKSPACE,
        "mounts": [Mount(path=WORKSPACE, writable=True)],
        "environment": {"PATH": r"C:\Python312"},
        "network": False,
        "limits": limits(),
    }
    declared.update(overrides)

    return SandboxRequest(**declared)  # type: ignore[arg-type]


def test_a_well_formed_request_is_valid() -> None:
    assert_valid(request())


def test_a_request_may_mount_a_read_only_directory_alongside_the_workspace() -> None:
    mounts = [Mount(path=WORKSPACE, writable=True), Mount(path=REFERENCE, writable=False)]

    assert_valid(request(mounts=mounts))
    assert writable_mounts(request(mounts=mounts)) == [Mount(path=WORKSPACE, writable=True)]


def test_a_request_without_a_step_id_is_invalid() -> None:
    with pytest.raises(InvalidSandboxRequestError, match="step"):
        assert_valid(request(step_id=""))


def test_a_request_without_a_program_is_invalid() -> None:
    with pytest.raises(InvalidSandboxRequestError, match="program"):
        assert_valid(request(program=""))


def test_a_request_without_mounts_is_invalid() -> None:
    with pytest.raises(InvalidSandboxRequestError, match="at least one mount"):
        assert_valid(request(mounts=[]))


def test_a_request_with_only_read_only_mounts_is_invalid() -> None:
    with pytest.raises(InvalidSandboxRequestError, match="one writable mount"):
        assert_valid(request(mounts=[Mount(path=WORKSPACE, writable=False)]))


def test_a_relative_mount_is_invalid() -> None:
    with pytest.raises(InvalidSandboxRequestError, match="absolute path"):
        assert_valid(request(mounts=[Mount(path="workspaces", writable=True)]))


def test_an_unresolved_mount_is_invalid() -> None:
    with pytest.raises(InvalidSandboxRequestError, match="absolute path"):
        assert_valid(request(mounts=[Mount(path=r"%TEMP%\work", writable=True)]))


def test_a_working_directory_outside_every_writable_mount_is_invalid() -> None:
    with pytest.raises(InvalidSandboxRequestError, match="outside every writable mount"):
        assert_valid(request(working_directory=r"C:\Users\x\elsewhere"))


def test_a_working_directory_in_a_read_only_mount_is_invalid() -> None:
    mounts = [Mount(path=WORKSPACE, writable=True), Mount(path=REFERENCE, writable=False)]

    with pytest.raises(InvalidSandboxRequestError, match="outside every writable mount"):
        assert_valid(request(working_directory=REFERENCE, mounts=mounts))


def test_a_working_directory_below_the_workspace_is_valid() -> None:
    assert_valid(request(working_directory=rf"{WORKSPACE}\src"))


def test_every_limit_must_be_positive() -> None:
    for absent in ("wall_clock_seconds", "memory_mb", "max_output_bytes"):
        with pytest.raises(InvalidSandboxRequestError, match="positive value"):
            assert_valid(request(limits=limits(**{absent: 0})))


def test_too_many_environment_variables_are_refused() -> None:
    crowded = {f"BISON_VAR_{index}": "1" for index in range(65)}

    with pytest.raises(InvalidSandboxRequestError, match="at most"):
        assert_valid(request(environment=crowded))


def test_an_empty_environment_is_valid() -> None:
    assert_valid(request(environment={}))


def test_unusable_environment_variable_names_are_refused() -> None:
    for name in ("", "PATH=X", " PATH"):
        with pytest.raises(InvalidSandboxRequestError, match="not usable"):
            assert_valid(request(environment={name: "1"}))


def test_a_native_program_is_recognised() -> None:
    assert program_kind(request(program="python")) == "native"
    assert program_kind(request(program=r"C:\Python312\python.exe")) == "native"


def test_a_wasm_module_is_recognised() -> None:
    assert program_kind(request(program=rf"{WORKSPACE}\count.wasm")) == "wasm_module"


def test_a_wasm_module_is_recognised_regardless_of_case() -> None:
    assert program_kind(request(program=rf"{WORKSPACE}\COUNT.WASM")) == "wasm_module"
