from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Final

DECLARABLE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "write_file",
        "run_python_script",
        "run_python_module",
        "install_python_packages",
    }
)

ACTION_REQUIRED_SERVICE: Final[str] = "task-runner"

MAX_CONTENT_CHARS: Final[int] = 200_000
MAX_ARGUMENTS: Final[int] = 32
MAX_PACKAGES: Final[int] = 32


class ActionSpecError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class WriteFile:
    path: str
    content: str
    TYPE: ClassVar[str] = "write_file"


@dataclass(frozen=True)
class RunPythonScript:
    script_path: str
    arguments: tuple[str, ...]
    TYPE: ClassVar[str] = "run_python_script"


@dataclass(frozen=True)
class RunPythonModule:
    module: str
    arguments: tuple[str, ...]
    TYPE: ClassVar[str] = "run_python_module"


@dataclass(frozen=True)
class InstallPythonPackages:
    packages: tuple[str, ...]
    TYPE: ClassVar[str] = "install_python_packages"


Action = WriteFile | RunPythonScript | RunPythonModule | InstallPythonPackages


def payload(action: Action) -> dict[str, Any]:
    fields = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in asdict(action).items()
    }

    return {"type": action.TYPE, **fields}


def written_paths(action: Action) -> tuple[str, ...]:
    if isinstance(action, WriteFile):
        return (action.path,)

    return ()


def installs_packages(action: Action) -> bool:
    return isinstance(action, InstallPythonPackages)


def text(source: dict[str, Any], key: str, label: str) -> str:
    value = source.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ActionSpecError(f"{label}.{key} must be a non-empty string")

    return value.strip()


def body(source: dict[str, Any], key: str, label: str) -> str:
    value = source.get(key)

    if not isinstance(value, str):
        raise ActionSpecError(f"{label}.{key} must be a string, and may be empty")

    if len(value) > MAX_CONTENT_CHARS:
        raise ActionSpecError(
            f"{label}.{key} must be under {MAX_CONTENT_CHARS} characters; "
            "split the file or write it in more than one step"
        )

    return value


def strings(source: dict[str, Any], key: str, label: str, limit: int) -> tuple[str, ...]:
    value = source.get(key, [])

    if value is None:
        return ()

    if not isinstance(value, list):
        raise ActionSpecError(f"{label}.{key} must be an array of strings")

    if len(value) > limit:
        raise ActionSpecError(f"{label}.{key} must hold no more than {limit} entries")

    collected: list[str] = []

    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ActionSpecError(f"{label}.{key}[{index}] must be a string")

        collected.append(item)

    return tuple(collected)


def named(source: dict[str, Any], key: str, label: str, limit: int) -> tuple[str, ...]:
    collected = strings(source, key, label, limit)

    for index, item in enumerate(collected):
        if not item.strip():
            raise ActionSpecError(f"{label}.{key}[{index}] must be a non-empty string")

    return tuple(item.strip() for item in collected)


def parse(entry: Any, label: str) -> Action:
    if not isinstance(entry, dict):
        raise ActionSpecError(f"{label} must be an object")

    declared = entry.get("type")

    if not isinstance(declared, str) or not declared:
        listed = ", ".join(sorted(DECLARABLE_TYPES))
        raise ActionSpecError(f"{label}.type must be one of {listed}")

    if declared not in DECLARABLE_TYPES:
        listed = ", ".join(sorted(DECLARABLE_TYPES))
        raise ActionSpecError(
            f"{label}.type {declared} is not an action this machine performs; use one of {listed}"
        )

    if declared == WriteFile.TYPE:
        return WriteFile(
            path=text(entry, "path", label),
            content=body(entry, "content", label),
        )

    if declared == RunPythonScript.TYPE:
        return RunPythonScript(
            script_path=text(entry, "script_path", label),
            arguments=strings(entry, "arguments", label, MAX_ARGUMENTS),
        )

    if declared == RunPythonModule.TYPE:
        return RunPythonModule(
            module=text(entry, "module", label),
            arguments=strings(entry, "arguments", label, MAX_ARGUMENTS),
        )

    packages = named(entry, "packages", label, MAX_PACKAGES)

    if not packages:
        raise ActionSpecError(f"{label}.packages must name at least one package")

    return InstallPythonPackages(packages=packages)


def parse_for(entry: Any, service: str, label: str) -> Action | None:
    if service != ACTION_REQUIRED_SERVICE:
        if entry is None:
            return None

        raise ActionSpecError(
            f"{label} must be null for a {service} step; only {ACTION_REQUIRED_SERVICE} "
            "steps carry an action"
        )

    if entry is None:
        listed = ", ".join(sorted(DECLARABLE_TYPES))
        raise ActionSpecError(
            f"{label} is required for a {ACTION_REQUIRED_SERVICE} step; name one of {listed}"
        )

    return parse(entry, label)
