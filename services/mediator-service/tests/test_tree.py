from __future__ import annotations

import json
from typing import Any

import pytest

from mediator_service.checks import FileExists, SqlResult
from mediator_service.tree import (
    MAX_CRITERIA_PER_TASK,
    MAX_TASKS,
    MediatorParseError,
    leaf_refs,
    parse,
)


def criterion(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "statement": "Table users exists in database bison_dev",
        "check_kind": "deterministic",
        "check_spec": {
            "type": "sql_result",
            "connection_ref": "bison_dev",
            "query": "select 1 from users",
            "expect": "row_count > 0",
        },
        "weight": 1,
    }
    base.update(overrides)

    return base


def task(ref: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ref": ref,
        "parent_ref": None,
        "title": f"Task {ref}",
        "description": "",
        "kind": "setup",
        "assigned_role": "engine",
        "depends_on": [],
        "criteria": [criterion()],
    }
    base.update(overrides)

    return base


def tree(*tasks: dict[str, Any], summary: str = "Provision the project") -> str:
    entries = list(tasks) if tasks else [task("a")]

    return json.dumps({"approach_summary": summary, "tasks": entries})


def test_a_well_formed_tree_parses() -> None:
    draft = parse(tree(task("setup"), task("build", depends_on=["setup"])))

    assert draft.approach_summary == "Provision the project"
    assert [item.ref for item in draft.tasks] == ["setup", "build"]
    assert draft.tasks[1].depends_on == ("setup",)


def test_a_criterion_carries_its_parsed_check_spec() -> None:
    draft = parse(tree())

    assert draft.tasks[0].criteria[0].check_spec == SqlResult(
        connection_ref="bison_dev", query="select 1 from users", expect="row_count > 0"
    )


def test_json_wrapped_in_prose_is_still_read() -> None:
    raw = f"Here is the tree you asked for:\n\n{tree()}\n\nLet me know if that works."

    assert parse(raw).tasks[0].ref == "a"


def test_positions_are_assigned_per_sibling_group_in_document_order() -> None:
    draft = parse(
        tree(
            task("a"),
            task("a.one", parent_ref="a"),
            task("b"),
            task("a.two", parent_ref="a"),
        )
    )
    positions = {item.ref: item.position for item in draft.tasks}

    assert positions == {"a": 0, "a.one": 0, "b": 1, "a.two": 1}


def test_the_model_does_not_get_to_write_its_own_position() -> None:
    draft = parse(tree(task("a", position=99)))

    assert draft.tasks[0].position == 0


def test_leaves_are_the_tasks_nobody_parents() -> None:
    draft = parse(
        tree(
            task("setup"),
            task("setup.db", parent_ref="setup"),
            task("setup.env", parent_ref="setup"),
            task("build"),
        )
    )

    assert leaf_refs(draft) == frozenset({"setup.db", "setup.env", "build"})


def test_a_deterministic_criterion_without_a_check_spec_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(tree(task("a", criteria=[criterion(check_spec=None)])))

    assert "how it is checked" in caught.value.detail


def test_an_inspected_criterion_carrying_a_check_spec_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(
            tree(
                task(
                    "a",
                    criteria=[
                        criterion(
                            check_kind="inspected",
                            check_spec={"type": "file_exists", "path": "out.txt"},
                        )
                    ],
                )
            )
        )

    assert "deterministic" in caught.value.detail


def test_an_inspected_criterion_with_no_check_spec_parses() -> None:
    draft = parse(
        tree(
            task(
                "a",
                criteria=[
                    criterion(
                        statement="The login page matches the uploaded reference",
                        check_kind="inspected",
                        check_spec=None,
                    )
                ],
            )
        )
    )

    assert draft.tasks[0].criteria[0].check_spec is None


def test_a_bad_check_spec_is_reported_with_its_full_path() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(
            tree(
                task("a"),
                task(
                    "b",
                    criteria=[
                        criterion(check_spec={"type": "port_open", "host": "127.0.0.1", "port": 0})
                    ],
                ),
            )
        )

    assert caught.value.detail.startswith("tasks[1].criteria[0].check_spec.port")


def test_a_refused_check_type_surfaces_through_the_tree() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(
            tree(
                task(
                    "a",
                    criteria=[
                        criterion(
                            check_spec={
                                "type": "process_exit",
                                "step_id": "s1",
                                "expected_code": 0,
                            }
                        )
                    ],
                )
            )
        )

    assert "no step exists" in caught.value.detail


def test_a_task_without_criteria_parses_here() -> None:
    draft = parse(tree(task("a", criteria=[])))

    assert draft.tasks[0].criteria == ()


def test_a_duplicate_ref_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(tree(task("a"), task("a")))

    assert "more than once" in caught.value.detail


def test_an_unknown_parent_ref_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(tree(task("a", parent_ref="ghost")))

    assert "ghost" in caught.value.detail


def test_an_unknown_dependency_ref_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(tree(task("a", depends_on=["ghost"])))

    assert "ghost" in caught.value.detail


def test_a_forward_reference_is_allowed() -> None:
    draft = parse(tree(task("a", depends_on=["b"]), task("b")))

    assert draft.tasks[0].depends_on == ("b",)


def test_repeated_dependencies_are_collapsed() -> None:
    draft = parse(tree(task("a"), task("b", depends_on=["a", "a"])))

    assert draft.tasks[1].depends_on == ("a",)


def test_a_dependency_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(MediatorParseError):
        parse(tree(task("a", depends_on=[7])))


@pytest.mark.parametrize("field", ["ref", "title"])
def test_a_required_string_cannot_be_blank(field: str) -> None:
    entry = task("a")
    entry[field] = "   "

    with pytest.raises(MediatorParseError) as caught:
        parse(tree(entry))

    assert field in caught.value.detail


def test_a_missing_description_becomes_empty() -> None:
    draft = parse(tree(task("a", description=None)))

    assert draft.tasks[0].description == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [("kind", "chores"), ("assigned_role", "inspector"), ("check_kind", "vibes")],
)
def test_a_value_outside_the_contract_is_refused(field: str, value: str) -> None:
    entry = (
        task("a", criteria=[criterion(**{field: value})])
        if field == "check_kind"
        else task("a", **{field: value})
    )

    with pytest.raises(MediatorParseError) as caught:
        parse(tree(entry))

    assert field in caught.value.detail


def test_a_missing_assigned_role_is_refused() -> None:
    entry = task("a")
    del entry["assigned_role"]

    with pytest.raises(MediatorParseError) as caught:
        parse(tree(entry))

    assert "assigned_role" in caught.value.detail


def test_a_missing_weight_defaults_to_one() -> None:
    entry = criterion()
    del entry["weight"]

    assert parse(tree(task("a", criteria=[entry]))).tasks[0].criteria[0].weight == 1


@pytest.mark.parametrize("weight", [0, 101, True])
def test_a_weight_outside_the_contract_is_refused(weight: object) -> None:
    with pytest.raises(MediatorParseError):
        parse(tree(task("a", criteria=[criterion(weight=weight)])))


def test_an_empty_tree_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(json.dumps({"approach_summary": "nothing to do", "tasks": []}))

    assert "non-empty" in caught.value.detail


def test_a_missing_approach_summary_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse(json.dumps({"tasks": [task("a")]}))

    assert "approach_summary" in caught.value.detail


def test_a_reply_with_no_json_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse("I would start by setting up the database, then the API.")

    assert "no JSON object" in caught.value.detail


def test_malformed_json_is_refused() -> None:
    with pytest.raises(MediatorParseError) as caught:
        parse('{"approach_summary": "x", "tasks": [}')

    assert "not valid JSON" in caught.value.detail


def test_a_json_array_is_refused() -> None:
    with pytest.raises(MediatorParseError):
        parse("[{}]")


def test_an_oversized_tree_is_refused() -> None:
    entries = [task(f"t{index}") for index in range(MAX_TASKS + 1)]

    with pytest.raises(MediatorParseError) as caught:
        parse(tree(*entries))

    assert str(MAX_TASKS) in caught.value.detail


def test_too_many_criteria_on_one_task_is_refused() -> None:
    entries = [criterion() for _ in range(MAX_CRITERIA_PER_TASK + 1)]

    with pytest.raises(MediatorParseError) as caught:
        parse(tree(task("a", criteria=entries)))

    assert str(MAX_CRITERIA_PER_TASK) in caught.value.detail


def test_a_file_exists_criterion_survives_the_round_trip() -> None:
    draft = parse(
        tree(
            task(
                "a",
                criteria=[
                    criterion(
                        statement="pyproject.toml exists in the project root",
                        check_spec={"type": "file_exists", "path": "pyproject.toml"},
                    )
                ],
            )
        )
    )

    assert draft.tasks[0].criteria[0].check_spec == FileExists(path="pyproject.toml")
