from __future__ import annotations

from typing import Any

import pytest

from mediator_service.dispatch import to_plan
from mediator_service.resume import (
    NotAwaitingConfirmationError,
    Parked,
    assert_confirmable,
    plan_payload,
    rebuild,
    step_payload,
    to_parked,
)

PLAN_ID = "pl-1"
SCOPE_ROOT = "C:\\scope"


def router_step(
    step_id: str = "s-1",
    position: int = 0,
    requires_confirmation: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "position": position,
        "description": f"step {step_id}",
        "service": "task-runner",
        "action": {"type": "run_python_script", "script_path": "build.py", "arguments": []},
        "requires_confirmation": requires_confirmation,
        "confirmation_reason": "it deletes files" if requires_confirmation else None,
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": ["c-1"],
        "effects": {
            "writes_paths": ["out.txt"],
            "deletes_paths": [],
            "network": False,
            "installs_packages": False,
            "needs_credentials": False,
            "drives_input": False,
            "reversible": True,
        },
        **extra,
    }


def stored_step(
    payload: dict[str, Any], plan_id: str = PLAN_ID, state: str = "awaiting_confirmation"
) -> dict[str, Any]:
    carried = {key: value for key, value in payload.items() if key != "step_id"}

    return {**carried, "id": payload["step_id"], "plan_id": plan_id, "state": state}


def router_plan(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": PLAN_ID,
        "project_id": "p-1",
        "task_id": "t-1",
        "request_id": "r-1",
        "scope_root": SCOPE_ROOT,
        "intent": "create the schema",
        "rationale": "the task asks for it",
        "steps": list(steps),
        "gated_count": sum(1 for step in steps if step["requires_confirmation"]),
        "model_id": "qwen2.5-coder:7b",
        "prompt_name": "router",
        "prompt_version": "v4",
        "prompt_hash": "d9223d1149c4",
    }


def stored_plan(payload: dict[str, Any], state: str = "awaiting_confirmation") -> dict[str, Any]:
    carried = {key: value for key, value in payload.items() if key != "plan_id"}

    return {
        **carried,
        "id": payload["plan_id"],
        "steps": [stored_step(step, payload["plan_id"], state) for step in payload["steps"]],
        "target_engine_id": None,
        "target_model_id": None,
        "steps_total": len(payload["steps"]),
        "attempts": 1,
        "repaired": False,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_a_stored_step_rebuilds_into_the_payload_the_router_sent() -> None:
    original = router_step()

    assert step_payload(stored_step(original)) == original


def test_a_field_the_router_adds_later_survives_the_round_trip() -> None:
    original = router_step(retries_allowed=3, tags=["slow", "network"])
    rebuilt = step_payload(stored_step(original))

    assert rebuilt["retries_allowed"] == 3
    assert rebuilt["tags"] == ["slow", "network"]
    assert rebuilt == original


def test_storage_bookkeeping_never_reaches_the_runner() -> None:
    rebuilt = step_payload(stored_step(router_step()))

    assert "id" not in rebuilt
    assert "plan_id" not in rebuilt
    assert "state" not in rebuilt


def test_the_step_id_is_taken_from_the_stored_row_id() -> None:
    assert step_payload(stored_step(router_step("s-7")))["step_id"] == "s-7"


def test_a_stored_plan_rebuilds_into_the_plan_the_router_produced() -> None:
    original = router_plan(router_step("s-1", 0), router_step("s-2", 1, False))

    assert rebuild(stored_plan(original)) == to_plan(original)


def test_the_plan_id_is_taken_from_the_stored_row_id() -> None:
    assert rebuild(stored_plan(router_plan(router_step()))).plan_id == PLAN_ID


def test_the_scope_root_survives_the_round_trip() -> None:
    assert rebuild(stored_plan(router_plan(router_step()))).scope_root == SCOPE_ROOT


def test_a_rebuilt_step_is_still_dispatchable() -> None:
    plan = rebuild(stored_plan(router_plan(router_step())))

    assert plan.steps[0].dispatchable


def test_a_rebuilt_step_keeps_the_effects_the_runner_judges_for_itself() -> None:
    original = router_step()
    plan = rebuild(stored_plan(router_plan(original)))

    assert plan.steps[0].effects == original["effects"]


def test_what_reaches_task_runner_is_the_router_shaped_payload() -> None:
    original = router_step()
    plan = rebuild(stored_plan(router_plan(original)))

    assert plan.steps[0].raw == original


def test_a_plan_with_no_steps_rebuilds_to_no_steps() -> None:
    assert rebuild(stored_plan(router_plan())).steps == ()


def test_an_entry_that_is_not_an_object_is_left_out() -> None:
    stored = stored_plan(router_plan(router_step()))
    stored["steps"] = [None, "s-2", *stored["steps"]]

    assert len(rebuild(stored).steps) == 1


def test_steps_that_are_not_a_list_are_read_as_none() -> None:
    stored = stored_plan(router_plan(router_step()))
    stored["steps"] = "everything"

    assert plan_payload(stored)["steps"] == []


def test_a_parked_step_reports_the_plan_it_belongs_to() -> None:
    parked = to_parked(stored_step(router_step("s-3")))

    assert parked == Parked(step_id="s-3", plan_id=PLAN_ID, state="awaiting_confirmation")


def test_a_step_awaiting_confirmation_can_be_confirmed() -> None:
    assert_confirmable(Parked("s-1", PLAN_ID, "awaiting_confirmation"))


@pytest.mark.parametrize("state", ["pending", "running", "succeeded", "failed", "aborted"])
def test_a_step_in_any_other_state_cannot_be_confirmed(state: str) -> None:
    with pytest.raises(NotAwaitingConfirmationError):
        assert_confirmable(Parked("s-1", PLAN_ID, state))


def test_the_refusal_names_the_step_and_the_state_it_found() -> None:
    with pytest.raises(NotAwaitingConfirmationError) as raised:
        assert_confirmable(Parked("s-4", PLAN_ID, "succeeded"))

    assert raised.value.step_id == "s-4"
    assert raised.value.state == "succeeded"


def test_a_step_with_no_state_at_all_is_refused_rather_than_assumed() -> None:
    with pytest.raises(NotAwaitingConfirmationError):
        assert_confirmable(to_parked({}))
