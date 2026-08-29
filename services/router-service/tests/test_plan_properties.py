from __future__ import annotations

import json
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from router_service.gating import PlanRejectedError, build
from router_service.plan import (
    FAILURE_POLICIES,
    INTENTS,
    SERVICES,
    RouterParseError,
    parse,
)

SCOPE = r"C:\Users\dev\bison\workspace"

json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=40),
)

json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=12), children, max_size=4),
    ),
    max_leaves=12,
)


def effects_payload() -> st.SearchStrategy[dict[str, Any]]:
    paths = st.lists(st.text(min_size=1, max_size=30), max_size=3)

    return st.fixed_dictionaries(
        {
            "writes_paths": paths,
            "deletes_paths": paths,
            "network": st.booleans(),
            "installs_packages": st.booleans(),
            "needs_credentials": st.booleans(),
            "drives_input": st.booleans(),
            "reversible": st.booleans(),
        }
    )


def action_payload() -> st.SearchStrategy[dict[str, Any]]:
    names = st.text(min_size=1, max_size=30).filter(lambda t: t.strip())
    arguments = st.lists(st.text(max_size=20), max_size=3)

    return st.one_of(
        st.fixed_dictionaries(
            {"type": st.just("write_file"), "path": names, "content": st.text(max_size=60)}
        ),
        st.fixed_dictionaries(
            {
                "type": st.just("run_python_script"),
                "script_path": names,
                "arguments": arguments,
            }
        ),
        st.fixed_dictionaries(
            {"type": st.just("run_python_module"), "module": names, "arguments": arguments}
        ),
        st.fixed_dictionaries(
            {
                "type": st.just("install_python_packages"),
                "packages": st.lists(names, min_size=1, max_size=3),
            }
        ),
    )


def step_payload(criterion_ids: list[str]) -> st.SearchStrategy[dict[str, Any]]:
    def with_service(service: str) -> st.SearchStrategy[dict[str, Any]]:
        chosen: st.SearchStrategy[Any] = action_payload() if service == "task-runner" else st.none()

        return st.fixed_dictionaries(
            {
                "description": st.text(min_size=1, max_size=200).filter(lambda t: t.strip()),
                "service": st.just(service),
                "action": chosen,
                "effects": effects_payload(),
                "on_failure": st.sampled_from(sorted(FAILURE_POLICIES)),
                "criterion_refs": st.lists(st.sampled_from(criterion_ids), min_size=1, max_size=3),
            }
        )

    return st.sampled_from(sorted(SERVICES)).flatmap(with_service)


def plan_payload(criterion_ids: list[str]) -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "intent": st.sampled_from(sorted(INTENTS)),
            "rationale": st.text(min_size=1, max_size=200).filter(lambda t: t.strip()),
            "steps": st.lists(step_payload(criterion_ids), min_size=1, max_size=6),
        }
    )


@given(json_values)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_arbitrary_json_never_crashes(value: Any) -> None:
    try:
        parse(json.dumps(value))
    except RouterParseError:
        return


@given(st.text(max_size=400))
@settings(max_examples=300)
def test_arbitrary_text_never_crashes(raw: str) -> None:
    try:
        parse(raw)
    except RouterParseError:
        return


@given(plan_payload(["c1", "c2"]), st.integers(min_value=1, max_value=400))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_truncation_never_crashes(payload: dict[str, Any], cut: int) -> None:
    try:
        parse(json.dumps(payload)[:cut])
    except RouterParseError:
        return


@given(plan_payload(["c1", "c2"]))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_a_well_formed_plan_always_parses(payload: dict[str, Any]) -> None:
    draft = parse(json.dumps(payload))

    assert len(draft.steps) == len(payload["steps"])


@given(plan_payload(["c1", "c2"]))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_gating_never_invents_a_reason(payload: dict[str, Any]) -> None:
    draft = parse(json.dumps(payload))

    try:
        plan = build(draft, SCOPE, ["c1", "c2"])
    except PlanRejectedError:
        return

    for step in plan.steps:
        assert (step.confirmation_reason is not None) == step.requires_confirmation


@given(plan_payload(["c1", "c2"]))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_an_approved_step_never_continues_on_failure(payload: dict[str, Any]) -> None:
    draft = parse(json.dumps(payload))

    try:
        plan = build(draft, SCOPE, ["c1", "c2"])
    except PlanRejectedError:
        return

    for step in plan.steps:
        assert not (step.requires_confirmation and step.on_failure == "continue")


@given(plan_payload(["c1", "c2"]))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_an_irreversible_step_is_always_gated(payload: dict[str, Any]) -> None:
    draft = parse(json.dumps(payload))

    try:
        plan = build(draft, SCOPE, ["c1", "c2"])
    except PlanRejectedError:
        return

    for step in plan.steps:
        if not step.reversible:
            assert step.requires_confirmation
