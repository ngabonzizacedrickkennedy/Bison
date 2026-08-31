from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

PYTHON: Final[str] = "python"

WRITE_FILE: Final[str] = "write_file"
RUN_PYTHON_SCRIPT: Final[str] = "run_python_script"
RUN_PYTHON_MODULE: Final[str] = "run_python_module"
INSTALL_PYTHON_PACKAGES: Final[str] = "install_python_packages"

RUNNABLE_TYPES: Final[frozenset[str]] = frozenset(
    {RUN_PYTHON_SCRIPT, RUN_PYTHON_MODULE, INSTALL_PYTHON_PACKAGES}
)


class UnrunnableActionError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Invocation:
    program: str
    arguments: tuple[str, ...]


def text(action: dict[str, Any], key: str, declared: str) -> str:
    value = action.get(key)

    if not isinstance(value, str) or not value.strip():
        raise UnrunnableActionError(f"a {declared} action needs a {key}")

    return value.strip()


def strings(action: dict[str, Any], key: str, declared: str) -> tuple[str, ...]:
    value = action.get(key, [])

    if value is None:
        return ()

    if not isinstance(value, list):
        raise UnrunnableActionError(f"a {declared} action needs {key} as an array of strings")

    for item in value:
        if not isinstance(item, str):
            raise UnrunnableActionError(f"every entry in {key} must be a string")

    return tuple(value)


def declared_type(action: dict[str, Any] | None) -> str:
    if action is None:
        raise UnrunnableActionError("this step carries no action and cannot be run")

    value = action.get("type")

    if not isinstance(value, str) or not value:
        raise UnrunnableActionError("this step's action does not say what kind it is")

    return value


def invocation(action: dict[str, Any] | None) -> Invocation:
    declared = declared_type(action)
    entry = action if action is not None else {}

    if declared == WRITE_FILE:
        raise UnrunnableActionError(
            "a write_file action is not a program and is carried out by the runner directly"
        )

    if declared not in RUNNABLE_TYPES:
        listed = ", ".join(sorted(RUNNABLE_TYPES))
        raise UnrunnableActionError(f"{declared} is not runnable; expected one of {listed}")

    if declared == RUN_PYTHON_SCRIPT:
        script = text(entry, "script_path", declared)

        return Invocation(
            program=PYTHON,
            arguments=(script, *strings(entry, "arguments", declared)),
        )

    if declared == RUN_PYTHON_MODULE:
        module = text(entry, "module", declared)

        return Invocation(
            program=PYTHON,
            arguments=("-m", module, *strings(entry, "arguments", declared)),
        )

    packages = strings(entry, "packages", declared)

    if not packages:
        raise UnrunnableActionError("an install action must name at least one package")

    return Invocation(
        program=PYTHON,
        arguments=("-m", "pip", "install", *packages),
    )


def runnable(action: dict[str, Any] | None) -> bool:
    return isinstance(action, dict) and action.get("type") in RUNNABLE_TYPES
