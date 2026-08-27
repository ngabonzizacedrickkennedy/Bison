from __future__ import annotations

import pytest

from mediator_service.sequencing import (
    BranchDependencyError,
    DependencyCycleError,
    DuplicateTaskError,
    Node,
    ParentCycleError,
    SelfDependencyError,
    UnknownTaskError,
    build,
)


def node(
    task_id: str,
    *,
    parent: str | None = None,
    depends_on: tuple[str, ...] = (),
    position: int = 0,
) -> Node:
    return Node(id=task_id, parent_id=parent, depends_on=depends_on, position=position)


def flat() -> list[Node]:
    return [
        node("a", position=0),
        node("b", depends_on=("a",), position=1),
        node("c", depends_on=("b",), position=2),
    ]


def nested() -> list[Node]:
    return [
        node("setup", position=0),
        node("setup.db", parent="setup", position=0),
        node("setup.env", parent="setup", position=1),
        node("build", depends_on=("setup",), position=1),
        node("build.api", parent="build", position=0),
        node("build.ui", parent="build", position=1),
    ]


def test_a_linear_chain_orders_in_declaration_order() -> None:
    assert build(flat()).order == ("a", "b", "c")


def test_only_leaves_are_ordered() -> None:
    ordering = build(nested())

    assert ordering.leaves == frozenset({"setup.db", "setup.env", "build.api", "build.ui"})
    assert "setup" not in ordering.order
    assert "build" not in ordering.order


def test_a_dependency_on_a_parent_waits_for_every_leaf_beneath_it() -> None:
    ordering = build(nested())

    assert ordering.dependencies("build.api") == ("setup.db", "setup.env")
    assert ordering.dependencies("build.ui") == ("setup.db", "setup.env")
    assert ordering.dependencies("setup.db") == ()


def test_the_same_tree_always_orders_the_same_way() -> None:
    forward = build(nested()).order
    reversed_input = build(list(reversed(nested()))).order
    shuffled = build([nested()[3], nested()[0], nested()[5], nested()[1], nested()[4], nested()[2]])

    assert forward == ("setup.db", "setup.env", "build.api", "build.ui")
    assert reversed_input == forward
    assert shuffled.order == forward


def test_position_decides_order_between_independent_siblings() -> None:
    tree = [
        node("root", position=0),
        node("root.second", parent="root", position=1),
        node("root.first", parent="root", position=0),
    ]

    assert build(tree).order == ("root.first", "root.second")


def test_the_next_task_is_the_first_whose_dependencies_are_settled() -> None:
    ordering = build(nested())

    assert ordering.next_task(frozenset()) == "setup.db"
    assert ordering.next_task(frozenset({"setup.db"})) == "setup.env"
    assert ordering.next_task(frozenset({"setup.db", "setup.env"})) == "build.api"
    assert ordering.next_task(frozenset({"setup.db", "setup.env", "build.api"})) == "build.ui"


def test_an_exhausted_tree_reports_no_next_task() -> None:
    ordering = build(flat())

    assert ordering.next_task(frozenset({"a", "b", "c"})) is None


def test_a_settled_task_is_never_offered_again() -> None:
    ordering = build(nested())

    assert "setup.db" not in ordering.ready(frozenset({"setup.db"}))


def test_independent_branches_are_all_ready_at_once() -> None:
    tree = [
        node("a", position=0),
        node("b", position=1),
        node("c", position=2),
    ]

    assert build(tree).ready(frozenset()) == ("a", "b", "c")


def test_what_blocks_a_task_is_reported_by_name() -> None:
    ordering = build(nested())

    assert ordering.blocked_by("build.api", frozenset()) == ("setup.db", "setup.env")
    assert ordering.blocked_by("build.api", frozenset({"setup.db"})) == ("setup.env",)
    assert ordering.blocked_by("build.api", frozenset({"setup.db", "setup.env"})) == ()


def test_a_declared_cycle_is_refused_and_names_the_cycle() -> None:
    tree = [
        node("a", depends_on=("c",), position=0),
        node("b", depends_on=("a",), position=1),
        node("c", depends_on=("b",), position=2),
    ]

    with pytest.raises(DependencyCycleError) as caught:
        build(tree)

    assert caught.value.lowered is False
    assert set(caught.value.cycle) == {"a", "b", "c"}
    assert "->" in str(caught.value)


def test_a_cycle_appears_only_once_dependencies_are_lowered() -> None:
    tree = [
        node("left", position=0),
        node("left.one", parent="left", position=0),
        node("left.two", parent="left", position=1),
        node("right", position=1),
        node("right.one", parent="right", position=0),
        node("right.two", parent="right", position=1),
    ]
    tree[1] = node("left.one", parent="left", depends_on=("right",), position=0)
    tree[4] = node("right.one", parent="right", depends_on=("left",), position=0)

    with pytest.raises(DependencyCycleError) as caught:
        build(tree)

    assert caught.value.lowered is True
    assert "lowered" in str(caught.value)


def test_a_parent_cycle_is_refused() -> None:
    tree = [
        node("a", parent="b", position=0),
        node("b", parent="a", position=1),
    ]

    with pytest.raises(ParentCycleError):
        build(tree)


def test_a_task_cannot_depend_on_its_own_ancestor() -> None:
    tree = [
        node("parent", position=0),
        node("parent.child", parent="parent", depends_on=("parent",), position=0),
    ]

    with pytest.raises(BranchDependencyError):
        build(tree)


def test_a_task_cannot_depend_on_its_own_descendant() -> None:
    tree = [
        node("parent", depends_on=("parent.child",), position=0),
        node("parent.child", parent="parent", position=0),
    ]

    with pytest.raises(BranchDependencyError):
        build(tree)


def test_a_self_dependency_is_refused() -> None:
    with pytest.raises(SelfDependencyError):
        build([node("a", depends_on=("a",), position=0)])


def test_a_duplicate_task_is_refused() -> None:
    with pytest.raises(DuplicateTaskError):
        build([node("a", position=0), node("a", position=1)])


def test_an_unknown_dependency_is_refused() -> None:
    with pytest.raises(UnknownTaskError):
        build([node("a", depends_on=("ghost",), position=0)])


def test_an_unknown_parent_is_refused() -> None:
    with pytest.raises(UnknownTaskError):
        build([node("a", parent="ghost", position=0)])


def test_a_settled_task_outside_the_tree_is_refused() -> None:
    ordering = build(flat())

    with pytest.raises(UnknownTaskError):
        ordering.ready(frozenset({"ghost"}))


def test_asking_about_a_task_outside_the_tree_is_refused() -> None:
    ordering = build(nested())

    with pytest.raises(UnknownTaskError):
        ordering.dependencies("setup")
