from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any, Final

SERVICE: Final[str] = "task-runner"

MAX_PATHS_NAMED: Final[int] = 3

UNRESOLVABLE_MARKERS: Final[tuple[str, ...]] = ("%", "$")


class ScopeRootError(RuntimeError):
    def __init__(self, scope_root: str) -> None:
        super().__init__(f"the scope root must be an absolute path, received {scope_root!r}")
        self.scope_root = scope_root


class StepRefusedError(RuntimeError):
    def __init__(self, refusals: list[str], requirements: list[str]) -> None:
        super().__init__("; ".join(refusals + requirements))
        self.refusals = refusals
        self.requirements = requirements


@dataclass(frozen=True)
class Verdict:
    admissible: bool
    refusals: list[str]
    requirements: list[str]


def segments(path: PureWindowsPath) -> list[str] | None:
    collected: list[str] = []

    for part in path.parts:
        if part == ".":
            continue

        if part == "..":
            if not collected:
                return None

            collected.pop()
            continue

        collected.append(part.lower())

    return collected


def root_segments(scope_root: str) -> list[str]:
    path = PureWindowsPath(scope_root)
    resolved = segments(path)

    if resolved is None or not path.is_absolute() or not resolved:
        raise ScopeRootError(scope_root)

    return resolved


def home_shorthand(path: PureWindowsPath) -> bool:
    for part in path.parts:
        if part in (".", ".."):
            continue

        return part == "~" or part.startswith("~\\") or part.startswith("~/")

    return False


def unresolvable(path: str) -> bool:
    if any(marker in path for marker in UNRESOLVABLE_MARKERS):
        return True

    candidate = PureWindowsPath(path)

    if home_shorthand(candidate):
        return True

    return bool(candidate.drive) and not candidate.is_absolute()


def contained(path: str, root: list[str]) -> bool:
    if unresolvable(path):
        return False

    candidate = PureWindowsPath(path)
    absolute = candidate if candidate.is_absolute() else PureWindowsPath(*root) / candidate
    resolved = segments(absolute)

    if resolved is None or len(resolved) < len(root):
        return False

    return resolved[: len(root)] == root


def escaped(paths: list[str], root: list[str]) -> list[str]:
    return [path for path in paths if not contained(path, root)]


def named(paths: list[str]) -> str:
    listed = ", ".join(paths[:MAX_PATHS_NAMED])
    remaining = len(paths) - min(len(paths), MAX_PATHS_NAMED)

    return f"{listed} and {remaining} more" if remaining > 0 else listed


def flag(payload: dict[str, Any], key: str, missing: bool) -> bool:
    value = payload.get(key)

    return value if isinstance(value, bool) else missing


def declared_paths(payload: dict[str, Any], key: str) -> list[str] | None:
    value = payload.get(key, [])

    if not isinstance(value, list):
        return None

    if not all(isinstance(entry, str) and entry for entry in value):
        return None

    return list(value)


def assess(step: dict[str, Any], scope_root: str, confirmed: bool) -> Verdict:
    root = root_segments(scope_root)
    service = step.get("service")
    raw = step.get("effects")
    effects = raw if isinstance(raw, dict) else {}

    refusals: list[str] = []
    requirements: list[str] = []

    if service != SERVICE:
        refusals.append(f"routed to {service!r}, which is not {SERVICE}")

    if not isinstance(raw, dict):
        refusals.append("declares no effects block")

    writes = declared_paths(effects, "writes_paths")
    deletes = declared_paths(effects, "deletes_paths")

    if writes is None:
        refusals.append("declares a malformed writes_paths")

    if deletes is None:
        refusals.append("declares a malformed deletes_paths")

    for label, declared in (("writes", writes), ("deletes", deletes)):
        outside = escaped(declared or [], root)

        if outside:
            refusals.append(f"{label} {named(outside)} outside the project directory")

    if flag(effects, "drives_input", True):
        refusals.append("declares that it moves the mouse or types, which task-runner never does")

    if deletes:
        requirements.append(f"deletes {len(deletes)} path(s) inside the project directory")

    if flag(effects, "needs_credentials", True):
        requirements.append("needs credentials")

    if flag(effects, "network", True):
        requirements.append("reaches the network")

    if flag(effects, "installs_packages", True):
        requirements.append("installs packages")

    if not flag(effects, "reversible", False):
        requirements.append("cannot be undone")

    admissible = not refusals and (confirmed or not requirements)

    return Verdict(admissible=admissible, refusals=refusals, requirements=requirements)


def assert_admissible(step: dict[str, Any], scope_root: str, confirmed: bool) -> None:
    verdict = assess(step, scope_root, confirmed)

    if verdict.admissible:
        return

    raise StepRefusedError(verdict.refusals, [] if confirmed else verdict.requirements)
