from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath

from router_service.plan import Effects, ProposedStep, RouterDraft

SAFE_FAILURE_POLICY = "abort"
MAX_PATHS_NAMED = 3


class PlanRejectedError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class GatedStep:
    position: int
    description: str
    service: str
    requires_confirmation: bool
    confirmation_reason: str | None
    on_failure: str
    reversible: bool
    criterion_refs: list[str]
    effects: Effects


@dataclass(frozen=True)
class GatedPlan:
    intent: str
    rationale: str
    steps: list[GatedStep]
    gated_count: int


def normalise(path: PureWindowsPath) -> list[str] | None:
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


def within(path: str, root: list[str]) -> bool:
    candidate = PureWindowsPath(path)
    absolute = candidate if candidate.is_absolute() else PureWindowsPath(*root) / candidate
    resolved = normalise(absolute)

    if resolved is None or len(resolved) < len(root):
        return False

    return resolved[: len(root)] == root


def outside(paths: list[str], root: list[str]) -> list[str]:
    return [path for path in paths if not within(path, root)]


def reasons(step: ProposedStep, root: list[str]) -> list[str]:
    effects = step.effects
    collected: list[str] = []

    if effects.deletes_paths:
        collected.append(f"deletes {len(effects.deletes_paths)} path(s)")

    escaped = outside(effects.writes_paths + effects.deletes_paths, root)

    if escaped:
        named = ", ".join(escaped[:MAX_PATHS_NAMED])
        remaining = len(escaped) - min(len(escaped), MAX_PATHS_NAMED)
        tail = f" and {remaining} more" if remaining > 0 else ""
        collected.append(f"touches {named}{tail} outside the project directory")

    if effects.needs_credentials:
        collected.append("needs credentials")

    if effects.network:
        collected.append("reaches the network")

    if effects.installs_packages:
        collected.append("installs packages")

    if effects.drives_input:
        collected.append("moves the mouse or types")

    if not effects.reversible:
        collected.append("cannot be undone")

    return collected


def gate(step: ProposedStep, position: int, root: list[str]) -> GatedStep:
    triggered = reasons(step, root)
    confirm = bool(triggered)
    demoted = confirm and step.on_failure == "continue"

    return GatedStep(
        position=position,
        description=step.description,
        service=step.service,
        requires_confirmation=confirm,
        confirmation_reason="; ".join(triggered) if confirm else None,
        on_failure=SAFE_FAILURE_POLICY if demoted else step.on_failure,
        reversible=step.effects.reversible,
        criterion_refs=step.criterion_refs,
        effects=step.effects,
    )


def unknown_refs(draft: RouterDraft, known: set[str]) -> list[str]:
    collected: list[str] = []

    for step in draft.steps:
        for reference in step.criterion_refs:
            if reference not in known and reference not in collected:
                collected.append(reference)

    return collected


def build(draft: RouterDraft, scope_root: str, criterion_ids: list[str]) -> GatedPlan:
    root = normalise(PureWindowsPath(scope_root))

    if root is None or not PureWindowsPath(scope_root).is_absolute():
        raise ValueError("the project scope root must be an absolute path")

    known = set(criterion_ids)
    invented = unknown_refs(draft, known)

    if invented:
        listed = ", ".join(invented[:MAX_PATHS_NAMED])
        raise PlanRejectedError(f"the plan references criteria that do not exist: {listed}")

    if known and not any(step.criterion_refs for step in draft.steps):
        raise PlanRejectedError("the plan advances none of this task's acceptance criteria")

    steps = [gate(step, position, root) for position, step in enumerate(draft.steps)]

    return GatedPlan(
        intent=draft.intent,
        rationale=draft.rationale,
        steps=steps,
        gated_count=sum(1 for step in steps if step.requires_confirmation),
    )
