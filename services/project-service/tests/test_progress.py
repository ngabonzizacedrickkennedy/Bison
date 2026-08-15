from __future__ import annotations

from project_service.progress import OVERALL_ID, Criterion, Task, compute


def build() -> tuple[list[Task], list[Criterion]]:
    tasks = [
        Task(id="root", parent_id=None, state="in_progress"),
        Task(id="a", parent_id="root", state="ready"),
        Task(id="b", parent_id="root", state="ready"),
    ]
    criteria = [
        Criterion(id="a1", task_id="a", weight=1, status="unverified"),
        Criterion(id="a2", task_id="a", weight=1, status="unverified"),
        Criterion(id="b1", task_id="b", weight=1, status="unverified"),
        Criterion(id="b2", task_id="b", weight=1, status="unverified"),
    ]
    return tasks, criteria


def test_nothing_verified_is_zero() -> None:
    tasks, criteria = build()
    result = compute(tasks, criteria)

    assert result[OVERALL_ID].percentage == 0.0
    assert result[OVERALL_ID].criteria_total == 4


def test_each_verification_moves_the_percentage() -> None:
    tasks, criteria = build()
    verified = [
        Criterion(id=c.id, task_id=c.task_id, weight=c.weight, status="verified")
        if c.id == "a1"
        else c
        for c in criteria
    ]

    result = compute(tasks, verified)

    assert result["a"].percentage == 50.0
    assert result[OVERALL_ID].percentage == 25.0


def test_ignored_criterion_leaves_the_denominator_and_raises_the_percentage() -> None:
    tasks, criteria = build()
    adjusted = []

    for c in criteria:
        if c.id == "a1":
            adjusted.append(
                Criterion(id=c.id, task_id=c.task_id, weight=c.weight, status="verified")
            )
        elif c.id == "a2":
            adjusted.append(
                Criterion(id=c.id, task_id=c.task_id, weight=c.weight, status="ignored")
            )
        else:
            adjusted.append(c)

    result = compute(tasks, adjusted)

    assert result["a"].percentage == 100.0
    assert result["a"].counted_weight == 1.0
    assert result[OVERALL_ID].percentage > 25.0


def test_failed_criterion_stays_in_the_denominator() -> None:
    tasks, criteria = build()
    adjusted = [
        Criterion(id=c.id, task_id=c.task_id, weight=c.weight, status="failed")
        if c.id == "a2"
        else c
        for c in criteria
    ]

    result = compute(tasks, adjusted)

    assert result["a"].counted_weight == 2.0
    assert result["a"].percentage == 0.0


def test_weights_are_respected() -> None:
    tasks = [Task(id="root", parent_id=None, state="ready")]
    criteria = [
        Criterion(id="c1", task_id="root", weight=3, status="verified"),
        Criterion(id="c2", task_id="root", weight=1, status="unverified"),
    ]

    result = compute(tasks, criteria)

    assert result["root"].percentage == 75.0


def test_ignored_task_leaves_the_parent_denominator() -> None:
    tasks, criteria = build()
    tasks = [
        Task(id=t.id, parent_id=t.parent_id, state="ignored") if t.id == "b" else t for t in tasks
    ]
    adjusted = [
        Criterion(id=c.id, task_id=c.task_id, weight=c.weight, status="verified")
        if c.task_id == "a"
        else c
        for c in criteria
    ]

    result = compute(tasks, adjusted)

    assert result[OVERALL_ID].percentage == 100.0
    assert result[OVERALL_ID].criteria_total == 2


def test_skipped_task_stays_in_the_parent_denominator() -> None:
    tasks, criteria = build()
    tasks = [
        Task(id=t.id, parent_id=t.parent_id, state="skipped") if t.id == "b" else t for t in tasks
    ]
    adjusted = [
        Criterion(id=c.id, task_id=c.task_id, weight=c.weight, status="verified")
        if c.task_id == "a"
        else c
        for c in criteria
    ]

    result = compute(tasks, adjusted)

    assert result[OVERALL_ID].percentage == 50.0
    assert result[OVERALL_ID].criteria_total == 4


def test_task_without_criteria_contributes_nothing() -> None:
    tasks = [
        Task(id="root", parent_id=None, state="ready"),
        Task(id="empty", parent_id="root", state="ready"),
    ]
    criteria = [Criterion(id="c1", task_id="root", weight=1, status="verified")]

    result = compute(tasks, criteria)

    assert result["empty"].counted_weight == 0.0
    assert result[OVERALL_ID].percentage == 100.0
