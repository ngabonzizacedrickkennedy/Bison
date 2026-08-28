from __future__ import annotations

import pytest

from mediator_service.checks import CheckSpec, FileExists
from mediator_service.discipline import (
    MAX_FINDINGS,
    TreeRejectedError,
    assert_disciplined,
    review,
)
from mediator_service.tree import DraftCriterion, DraftTask, TreeDraft

SPEC: CheckSpec = FileExists(path="out.txt")


def deterministic(statement: str, weight: int = 1) -> DraftCriterion:
    return DraftCriterion(
        statement=statement, check_kind="deterministic", check_spec=SPEC, weight=weight
    )


def inspected(statement: str, weight: int = 1) -> DraftCriterion:
    return DraftCriterion(
        statement=statement, check_kind="inspected", check_spec=None, weight=weight
    )


def task(
    ref: str,
    *criteria: DraftCriterion,
    parent: str | None = None,
    kind: str = "code",
) -> DraftTask:
    return DraftTask(
        ref=ref,
        parent_ref=parent,
        title=f"Task {ref}",
        description="",
        kind=kind,
        assigned_role="engine",
        depends_on=(),
        criteria=criteria,
        position=0,
    )


def draft(*tasks: DraftTask) -> TreeDraft:
    return TreeDraft(approach_summary="Provision the project", tasks=tasks)


def test_a_disciplined_tree_has_nothing_to_report() -> None:
    tree = draft(
        task("db", deterministic("Table users exists in database bison_dev")),
        task("api", deterministic("The file src/api.py is present")),
    )

    assert review(tree) == ()


def test_the_prompt_s_own_example_of_a_good_criterion_passes() -> None:
    tree = draft(task("db", deterministic("Table users exists in database bison_dev")))

    assert review(tree) == ()


def test_the_prompt_s_own_example_of_a_bad_criterion_is_rejected() -> None:
    tree = draft(task("db", deterministic("The database is set up")))
    findings = review(tree)

    assert len(findings) == 1
    assert "summary rather than a criterion" in findings[0]


def test_an_inspected_criterion_a_check_could_settle_is_rejected() -> None:
    tree = draft(
        task(
            "db",
            deterministic("The file schema.sql is present"),
            inspected("Table users exists in database bison_dev"),
        )
    )
    findings = review(tree)

    assert any("make it deterministic" in item for item in findings)


def test_a_judgement_signal_overrides_a_mechanical_word() -> None:
    tree = draft(
        task(
            "ui",
            deterministic("The file src/table.tsx is present"),
            inspected("The results table matches the reference screenshot"),
        )
    )

    assert review(tree) == ()


def test_a_windows_path_is_recognised_as_mechanically_checkable() -> None:
    tree = draft(
        task(
            "scaffold",
            deterministic("The file marker.txt is present"),
            inspected(r"The path C:\bison\scratch is present"),
        )
    )
    findings = review(tree)

    assert any("make it deterministic" in item for item in findings)


def test_a_url_is_recognised_as_mechanically_checkable() -> None:
    tree = draft(
        task(
            "serve",
            deterministic("The file server.py is present"),
            inspected("A request to https://127.0.0.1/health comes back"),
        )
    )
    findings = review(tree)

    assert any("make it deterministic" in item for item in findings)


def test_a_genuine_judgement_criterion_is_left_alone() -> None:
    tree = draft(
        task(
            "ui",
            deterministic("The file index.html is present"),
            inspected("The heading font matches the supplied design"),
        )
    )

    assert review(tree) == ()


def test_exit_code_phrasing_points_at_an_observable_result() -> None:
    tree = draft(task("build", deterministic("The build command returns 0")))
    findings = review(tree)

    assert any("observable result" in item for item in findings)


def test_a_compound_criterion_is_asked_to_be_split() -> None:
    tree = draft(task("db", deterministic("Table users exists and table roles exists")))
    findings = review(tree)

    assert any("one thing per criterion" in item for item in findings)


def test_a_leaf_with_no_criteria_is_rejected() -> None:
    findings = review(draft(task("orphan")))

    assert len(findings) == 1
    assert "nothing could ever mark it done" in findings[0]


def test_a_leaf_settled_only_by_judgement_is_rejected() -> None:
    tree = draft(task("ui", inspected("The heading font matches the supplied design")))
    findings = review(tree)

    assert any("rests on evidence" in item for item in findings)


def test_a_real_world_leaf_may_be_settled_by_judgement_alone() -> None:
    tree = draft(
        task(
            "vendor",
            inspected("The signed contract is delivered to the vendor in person"),
            kind="real_world",
        )
    )

    assert review(tree) == ()


def test_a_real_world_leaf_still_needs_some_criterion() -> None:
    findings = review(draft(task("vendor", kind="real_world")))

    assert len(findings) == 1
    assert "nothing could ever mark it done" in findings[0]


def test_criteria_on_a_parent_belong_on_its_leaves() -> None:
    tree = draft(
        task("setup", deterministic("The file setup.log is present")),
        task("setup.db", deterministic("Table users exists in database bison_dev"), parent="setup"),
    )
    findings = review(tree)

    assert len(findings) == 1
    assert "belong on the leaves" in findings[0]


def test_a_parent_without_criteria_is_fine() -> None:
    tree = draft(
        task("setup"),
        task("setup.db", deterministic("Table users exists in database bison_dev"), parent="setup"),
    )

    assert review(tree) == ()


def test_the_same_criterion_stated_twice_is_rejected() -> None:
    tree = draft(
        task(
            "db",
            deterministic("Table users exists in database bison_dev"),
            deterministic("Table users exists in database bison_dev", weight=5),
        )
    )
    findings = review(tree)

    assert any("weight against progress twice" in item for item in findings)


def test_punctuation_does_not_hide_a_duplicate() -> None:
    tree = draft(
        task(
            "db",
            deterministic("Table users exists in database bison_dev"),
            deterministic("Table users, exists in database bison_dev!"),
        )
    )
    findings = review(tree)

    assert any("weight against progress twice" in item for item in findings)


def test_every_problem_is_reported_in_one_pass() -> None:
    tree = draft(
        task("a", deterministic("The database is set up")),
        task("b"),
        task("c", deterministic("The build command returns 0")),
    )
    findings = review(tree)

    assert len(findings) == 3


def test_the_findings_are_capped_so_the_repair_stays_readable() -> None:
    tree = draft(*(task(f"t{index}") for index in range(MAX_FINDINGS + 8)))

    assert len(review(tree)) == MAX_FINDINGS


def test_a_finding_names_the_task_it_came_from() -> None:
    findings = review(draft(task("provision-db")))

    assert "provision-db" in findings[0]


def test_asserting_discipline_raises_with_every_finding() -> None:
    tree = draft(task("a", deterministic("The database is set up")), task("b"))

    with pytest.raises(TreeRejectedError) as caught:
        assert_disciplined(tree)

    assert len(caught.value.findings) == 2


def test_asserting_discipline_stays_quiet_on_a_good_tree() -> None:
    tree = draft(task("db", deterministic("Table users exists in database bison_dev")))

    assert_disciplined(tree)
