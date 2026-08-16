from __future__ import annotations

from router_service.context import (
    BriefFacts,
    Criterion,
    HistoryEntry,
    RouterContext,
    TaskFacts,
    criterion_ids,
    render,
)

SCOPE = r"C:\Users\dev\bison\workspace"


def criterion(index: int) -> Criterion:
    return Criterion(
        criterion_id=f"c{index}",
        statement=f"Table number {index} exists in the database",
        check_kind="deterministic",
        status="unverified",
    )


def context(**overrides: object) -> RouterContext:
    base: dict[str, object] = {
        "task": TaskFacts(
            title="Provision the project database",
            description="Create the schema and seed reference data",
            kind="code",
            state="ready",
        ),
        "criteria": [criterion(1), criterion(2)],
        "scope_root": SCOPE,
        "brief": BriefFacts(
            interpreted_goal="Match every invoice to a payment",
            project_type="code",
            known_constraints=["runs offline"],
            out_of_scope=["tax filing"],
            assumptions=["amounts are in RWF"],
        ),
        "history": [HistoryEntry(title=f"Earlier task {n}", state="done") for n in range(12)],
    }
    base.update(overrides)

    return RouterContext(**base)  # type: ignore[arg-type]


def test_renders_every_section() -> None:
    rendered = render(context())

    assert "TASK" in rendered
    assert "ACCEPTANCE CRITERIA" in rendered
    assert "WORKING DIRECTORY" in rendered
    assert "PROJECT" in rendered
    assert "RECENT TASKS" in rendered


def test_the_working_directory_is_stated_verbatim() -> None:
    assert SCOPE in render(context())


def test_criteria_carry_their_ids() -> None:
    rendered = render(context())

    assert "c1" in rendered
    assert "c2" in rendered


def test_criteria_carry_status_and_check_kind() -> None:
    assert "[unverified/deterministic]" in render(context())


def test_a_task_with_no_criteria_says_so() -> None:
    rendered = render(context(criteria=[]))

    assert "none recorded for this task" in rendered


def test_a_missing_brief_drops_only_that_section() -> None:
    rendered = render(context(brief=None))

    assert "PROJECT" not in rendered
    assert "ACCEPTANCE CRITERIA" in rendered


def test_history_shrinks_before_anything_else_is_lost() -> None:
    full = context()
    squeezed = render(full, budget=len(render(full)) - 200)

    assert "c1" in squeezed
    assert "c2" in squeezed
    assert SCOPE in squeezed
    assert "Earlier task 11" not in squeezed


def test_criteria_survive_a_budget_that_kills_all_history() -> None:
    full = context()
    squeezed = render(full, budget=400)

    assert "c1" in squeezed
    assert "RECENT TASKS" not in squeezed


def test_history_is_capped_before_any_budget_pressure() -> None:
    many = context(history=[HistoryEntry(title=f"Task {n}", state="done") for n in range(40)])
    rendered = render(many)

    assert "(12 of 40)" in rendered


def test_a_long_description_is_truncated_rather_than_dropped() -> None:
    verbose = TaskFacts(
        title="Provision the project database",
        description="x" * 9000,
        kind="code",
        state="ready",
    )
    rendered = render(context(task=verbose))

    assert "[...truncated]" in rendered
    assert "Provision the project database" in rendered


def test_criterion_ids_matches_what_was_rendered() -> None:
    assert criterion_ids(context()) == ["c1", "c2"]
