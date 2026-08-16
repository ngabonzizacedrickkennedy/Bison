from __future__ import annotations

import pytest

from router_service.gating import PlanRejectedError, build
from router_service.plan import Effects, ProposedStep, RouterDraft

SCOPE = r"C:\Users\dev\bison\workspace"
CRITERION = "c1"


def effects(**overrides: object) -> Effects:
    base: dict[str, object] = {
        "writes_paths": [],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    base.update(overrides)

    return Effects(**base)  # type: ignore[arg-type]


def step(**overrides: object) -> ProposedStep:
    base: dict[str, object] = {
        "description": "Write the reconciliation module",
        "service": "task-runner",
        "effects": effects(),
        "on_failure": "abort",
        "criterion_refs": [CRITERION],
    }
    base.update(overrides)

    return ProposedStep(**base)  # type: ignore[arg-type]


def draft(*steps: ProposedStep) -> RouterDraft:
    return RouterDraft(
        intent="dev_task",
        rationale="the task asks for a module to be written",
        steps=list(steps) or [step()],
    )


def test_a_harmless_step_is_not_gated() -> None:
    plan = build(draft(), SCOPE, [CRITERION])

    assert plan.steps[0].requires_confirmation is False
    assert plan.steps[0].confirmation_reason is None
    assert plan.gated_count == 0


@pytest.mark.parametrize(
    ("flag", "fragment"),
    [
        ("network", "reaches the network"),
        ("installs_packages", "installs packages"),
        ("needs_credentials", "needs credentials"),
        ("drives_input", "moves the mouse or types"),
    ],
)
def test_each_declared_effect_gates_on_its_own(flag: str, fragment: str) -> None:
    plan = build(draft(step(effects=effects(**{flag: True}))), SCOPE, [CRITERION])
    gated = plan.steps[0]

    assert gated.requires_confirmation is True
    assert gated.confirmation_reason is not None
    assert fragment in gated.confirmation_reason


def test_an_irreversible_step_is_gated() -> None:
    plan = build(draft(step(effects=effects(reversible=False))), SCOPE, [CRITERION])

    assert plan.steps[0].requires_confirmation is True
    assert "cannot be undone" in (plan.steps[0].confirmation_reason or "")
    assert plan.steps[0].reversible is False


def test_a_deletion_is_gated_even_inside_scope() -> None:
    inside = [rf"{SCOPE}\build\stale.txt"]
    plan = build(draft(step(effects=effects(deletes_paths=inside))), SCOPE, [CRITERION])

    assert "deletes 1 path(s)" in (plan.steps[0].confirmation_reason or "")


def test_a_write_inside_scope_is_not_gated() -> None:
    plan = build(
        draft(step(effects=effects(writes_paths=["src/reconcile.py"]))), SCOPE, [CRITERION]
    )

    assert plan.steps[0].requires_confirmation is False


def test_an_absolute_write_inside_scope_is_not_gated() -> None:
    inside = [rf"{SCOPE}\src\reconcile.py"]
    plan = build(draft(step(effects=effects(writes_paths=inside))), SCOPE, [CRITERION])

    assert plan.steps[0].requires_confirmation is False


def test_scope_matching_ignores_case() -> None:
    shouting = [SCOPE.upper() + r"\SRC\RECONCILE.PY"]
    plan = build(draft(step(effects=effects(writes_paths=shouting))), SCOPE, [CRITERION])

    assert plan.steps[0].requires_confirmation is False


def test_a_write_outside_scope_is_gated() -> None:
    outside = [r"C:\Windows\System32\drivers\etc\hosts"]
    plan = build(draft(step(effects=effects(writes_paths=outside))), SCOPE, [CRITERION])

    assert "outside the project directory" in (plan.steps[0].confirmation_reason or "")


def test_a_relative_escape_is_caught() -> None:
    escape = [r"..\..\..\Windows\System32\config"]
    plan = build(draft(step(effects=effects(writes_paths=escape))), SCOPE, [CRITERION])

    assert "outside the project directory" in (plan.steps[0].confirmation_reason or "")


def test_an_escape_that_returns_inside_is_not_gated() -> None:
    wandering = [r"src\..\src\reconcile.py"]
    plan = build(draft(step(effects=effects(writes_paths=wandering))), SCOPE, [CRITERION])

    assert plan.steps[0].requires_confirmation is False


def test_continue_is_demoted_to_abort_on_a_gated_step() -> None:
    risky = step(effects=effects(network=True), on_failure="continue")
    plan = build(draft(risky), SCOPE, [CRITERION])

    assert plan.steps[0].on_failure == "abort"


def test_continue_survives_on_a_step_nobody_has_to_approve() -> None:
    plan = build(draft(step(on_failure="continue")), SCOPE, [CRITERION])

    assert plan.steps[0].on_failure == "continue"


def test_retry_survives_gating() -> None:
    risky = step(effects=effects(network=True), on_failure="retry")
    plan = build(draft(risky), SCOPE, [CRITERION])

    assert plan.steps[0].on_failure == "retry"


def test_several_triggers_are_all_named() -> None:
    loaded = step(effects=effects(network=True, needs_credentials=True, reversible=False))
    plan = build(draft(loaded), SCOPE, [CRITERION])
    reason = plan.steps[0].confirmation_reason or ""

    assert "needs credentials" in reason
    assert "reaches the network" in reason
    assert "cannot be undone" in reason


def test_positions_are_assigned_in_order() -> None:
    plan = build(draft(step(), step(), step()), SCOPE, [CRITERION])

    assert [gated.position for gated in plan.steps] == [0, 1, 2]


def test_gated_count_counts_only_gated_steps() -> None:
    plan = build(draft(step(), step(effects=effects(network=True)), step()), SCOPE, [CRITERION])

    assert plan.gated_count == 1


def test_an_invented_criterion_is_refused() -> None:
    with pytest.raises(PlanRejectedError, match="do not exist"):
        build(draft(step(criterion_refs=["c9"])), SCOPE, [CRITERION])


def test_a_plan_advancing_nothing_is_refused() -> None:
    with pytest.raises(PlanRejectedError, match="advances none"):
        build(draft(step(criterion_refs=[])), SCOPE, [CRITERION])


def test_a_task_with_no_criteria_accepts_empty_refs() -> None:
    plan = build(draft(step(criterion_refs=[])), SCOPE, [])

    assert plan.steps[0].criterion_refs == []


def test_a_relative_scope_root_is_refused() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        build(draft(), r"workspace\bison", [CRITERION])
