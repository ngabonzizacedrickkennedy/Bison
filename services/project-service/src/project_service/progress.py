from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    id: str
    task_id: str
    weight: int
    status: str


@dataclass(frozen=True)
class Task:
    id: str
    parent_id: str | None
    state: str


@dataclass(frozen=True)
class Progress:
    task_id: str
    percentage: float
    verified_weight: float
    counted_weight: float
    criteria_total: int
    criteria_verified: int
    criteria_failed: int
    criteria_ignored: int


COUNTED_EXCLUSIONS = frozenset({"ignored"})

OVERALL_ID = "__project__"


def _empty(task_id: str) -> Progress:
    return Progress(
        task_id=task_id,
        percentage=0.0,
        verified_weight=0.0,
        counted_weight=0.0,
        criteria_total=0,
        criteria_verified=0,
        criteria_failed=0,
        criteria_ignored=0,
    )


def _tally(task_id: str, criteria: list[Criterion]) -> Progress:
    if not criteria:
        return _empty(task_id)

    counted = [c for c in criteria if c.status not in COUNTED_EXCLUSIONS]
    counted_weight = float(sum(c.weight for c in counted))
    verified_weight = float(sum(c.weight for c in counted if c.status == "verified"))

    percentage = 100.0 if counted_weight == 0.0 else verified_weight / counted_weight * 100.0

    return Progress(
        task_id=task_id,
        percentage=round(percentage, 4),
        verified_weight=verified_weight,
        counted_weight=counted_weight,
        criteria_total=len(criteria),
        criteria_verified=sum(1 for c in criteria if c.status == "verified"),
        criteria_failed=sum(1 for c in criteria if c.status == "failed"),
        criteria_ignored=sum(1 for c in criteria if c.status == "ignored"),
    )


def _merge(task_id: str, parts: list[Progress]) -> Progress:
    verified_weight = sum(p.verified_weight for p in parts)
    counted_weight = sum(p.counted_weight for p in parts)

    percentage = 100.0 if counted_weight == 0.0 else verified_weight / counted_weight * 100.0

    return Progress(
        task_id=task_id,
        percentage=round(percentage, 4),
        verified_weight=verified_weight,
        counted_weight=counted_weight,
        criteria_total=sum(p.criteria_total for p in parts),
        criteria_verified=sum(p.criteria_verified for p in parts),
        criteria_failed=sum(p.criteria_failed for p in parts),
        criteria_ignored=sum(p.criteria_ignored for p in parts),
    )


def compute(tasks: list[Task], criteria: list[Criterion]) -> dict[str, Progress]:
    by_task: dict[str, list[Criterion]] = {task.id: [] for task in tasks}

    for criterion in criteria:
        if criterion.task_id in by_task:
            by_task[criterion.task_id].append(criterion)

    children: dict[str | None, list[str]] = {}

    for task in tasks:
        children.setdefault(task.parent_id, []).append(task.id)

    states = {task.id: task.state for task in tasks}
    resolved: dict[str, Progress] = {}

    def resolve(task_id: str) -> Progress:
        cached = resolved.get(task_id)

        if cached is not None:
            return cached

        own = _tally(task_id, by_task.get(task_id, []))
        parts = [own]

        for child_id in children.get(task_id, []):
            child = resolve(child_id)

            if states.get(child_id) == "ignored":
                continue

            parts.append(child)

        merged = _merge(task_id, parts)
        resolved[task_id] = merged
        return merged

    for task in tasks:
        resolve(task.id)

    roots = [
        resolved[task_id] for task_id in children.get(None, []) if states.get(task_id) != "ignored"
    ]

    resolved[OVERALL_ID] = _merge(OVERALL_ID, roots) if roots else _empty(OVERALL_ID)

    return resolved
