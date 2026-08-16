from __future__ import annotations

import json
from typing import Any

import pytest

from router_service.plan import MAX_STEPS, RouterParseError, parse


def effects(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "writes_paths": ["src/reconcile.py"],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    base.update(overrides)

    return base


def step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "description": "Write the reconciliation module",
        "service": "task-runner",
        "effects": effects(),
        "on_failure": "abort",
        "criterion_refs": ["c1"],
    }
    base.update(overrides)

    return base


def payload(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "intent": "dev_task",
        "rationale": "the task asks for a module to be written",
        "steps": [step()],
    }
    base.update(overrides)

    return json.dumps(base)


def test_parses_a_clean_plan() -> None:
    draft = parse(payload())

    assert draft.intent == "dev_task"
    assert len(draft.steps) == 1
    assert draft.steps[0].service == "task-runner"
    assert draft.steps[0].criterion_refs == ["c1"]


def test_survives_a_fenced_response() -> None:
    fenced = f"Here is the plan:\n```json\n{payload()}\n```\n"

    assert parse(fenced).intent == "dev_task"


def test_rejects_a_response_with_no_object() -> None:
    with pytest.raises(RouterParseError, match="no JSON object"):
        parse("I cannot help with that.")


def test_rejects_malformed_json() -> None:
    with pytest.raises(RouterParseError, match="not valid JSON"):
        parse('{"intent": "dev_task", "steps": [}')


def test_rejects_an_unknown_intent() -> None:
    with pytest.raises(RouterParseError, match="intent must be one of"):
        parse(payload(intent="delete_everything"))


def test_rejects_an_unknown_service() -> None:
    with pytest.raises(RouterParseError, match=r"steps\[0\].service"):
        parse(payload(steps=[step(service="kubernetes")]))


def test_rejects_an_empty_plan() -> None:
    with pytest.raises(RouterParseError, match="non-empty array"):
        parse(payload(steps=[]))


def test_rejects_a_plan_beyond_the_cap() -> None:
    with pytest.raises(RouterParseError, match="more than"):
        parse(payload(steps=[step()] * (MAX_STEPS + 1)))


def test_rejects_an_overlong_description() -> None:
    with pytest.raises(RouterParseError, match="under 500 characters"):
        parse(payload(steps=[step(description="x" * 501)]))


def test_rejects_a_step_that_is_not_an_object() -> None:
    with pytest.raises(RouterParseError, match=r"steps\[0\] must be an object"):
        parse(payload(steps=["write the module"]))


def test_a_missing_effects_object_is_risky_on_every_axis() -> None:
    draft = parse(payload(steps=[step(effects=None)]))
    parsed = draft.steps[0].effects

    assert parsed.network is True
    assert parsed.installs_packages is True
    assert parsed.needs_credentials is True
    assert parsed.drives_input is True
    assert parsed.reversible is False


def test_a_non_boolean_flag_is_read_as_risky() -> None:
    draft = parse(payload(steps=[step(effects=effects(network="no"))]))

    assert draft.steps[0].effects.network is True


def test_a_missing_flag_is_read_as_risky() -> None:
    partial = effects()
    del partial["needs_credentials"]
    draft = parse(payload(steps=[step(effects=partial)]))

    assert draft.steps[0].effects.needs_credentials is True


def test_a_missing_reversible_is_read_as_irreversible() -> None:
    partial = effects()
    del partial["reversible"]
    draft = parse(payload(steps=[step(effects=partial)]))

    assert draft.steps[0].effects.reversible is False


def test_an_absent_failure_policy_defaults_to_abort() -> None:
    partial = step()
    del partial["on_failure"]

    assert parse(payload(steps=[partial])).steps[0].on_failure == "abort"


def test_an_unknown_failure_policy_is_refused() -> None:
    with pytest.raises(RouterParseError, match=r"steps\[0\].on_failure"):
        parse(payload(steps=[step(on_failure="ignore")]))


def test_criterion_refs_are_deduplicated_in_order() -> None:
    draft = parse(payload(steps=[step(criterion_refs=["c2", "c1", "c2", " c1 "])]))

    assert draft.steps[0].criterion_refs == ["c2", "c1"]


def test_absent_criterion_refs_read_as_empty() -> None:
    partial = step()
    del partial["criterion_refs"]

    assert parse(payload(steps=[partial])).steps[0].criterion_refs == []


def test_rejects_paths_that_are_not_an_array() -> None:
    with pytest.raises(RouterParseError, match="array of strings"):
        parse(payload(steps=[step(effects=effects(writes_paths="src/reconcile.py"))]))


def test_rejects_a_missing_rationale() -> None:
    with pytest.raises(RouterParseError, match="rationale must be"):
        parse(payload(rationale=""))
