from __future__ import annotations

from router_service.gating import build
from router_service.persist import plan_payload
from router_service.plan import Effects, ProposedStep, RouterDraft
from router_service.router import RouterRun

SCOPE = r"C:\Users\dev\bison\workspace"
CRITERION = "c1"
REQUEST = "11111111-1111-1111-1111-111111111111"


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


def run(*steps: ProposedStep, attempts: int = 1) -> RouterRun:
    draft = RouterDraft(
        intent="dev_task",
        rationale="the task asks for a module to be written",
        steps=list(steps) or [step()],
    )

    return RouterRun(
        plan=build(draft, SCOPE, [CRITERION]),
        model_id="qwen2.5-coder:7b",
        prompt_name="router",
        prompt_version="v3",
        prompt_hash="7d997b13170f",
        attempts=attempts,
        repaired=attempts > 1,
    )


def test_payload_carries_provenance() -> None:
    payload = plan_payload(run(), REQUEST, SCOPE)

    assert payload["request_id"] == REQUEST
    assert payload["scope_root"] == SCOPE
    assert payload["model_id"] == "qwen2.5-coder:7b"
    assert payload["prompt_name"] == "router"
    assert payload["prompt_version"] == "v3"
    assert payload["prompt_hash"] == "7d997b13170f"


def test_payload_records_a_repair() -> None:
    payload = plan_payload(run(attempts=2), REQUEST, SCOPE)

    assert payload["attempts"] == 2
    assert payload["repaired"] is True


def test_steps_are_emitted_in_position_order() -> None:
    payload = plan_payload(
        run(step(description="first"), step(description="second"), step(description="third")),
        REQUEST,
        SCOPE,
    )

    assert [entry["description"] for entry in payload["steps"]] == ["first", "second", "third"]


def test_a_gated_step_carries_its_reason() -> None:
    payload = plan_payload(run(step(effects=effects(network=True))), REQUEST, SCOPE)
    entry = payload["steps"][0]

    assert entry["requires_confirmation"] is True
    assert entry["confirmation_reason"] is not None
    assert "network" in entry["confirmation_reason"]


def test_an_ungated_step_carries_no_reason() -> None:
    entry = plan_payload(run(), REQUEST, SCOPE)["steps"][0]

    assert entry["requires_confirmation"] is False
    assert entry["confirmation_reason"] is None


def test_effects_survive_whole() -> None:
    declared = effects(writes_paths=["ledger.db"], network=True, reversible=False)
    entry = plan_payload(run(step(effects=declared)), REQUEST, SCOPE)["steps"][0]

    assert entry["effects"]["writes_paths"] == ["ledger.db"]
    assert entry["effects"]["network"] is True
    assert entry["effects"]["reversible"] is False


def test_demotion_to_abort_reaches_the_payload() -> None:
    entry = plan_payload(
        run(step(effects=effects(network=True), on_failure="continue")), REQUEST, SCOPE
    )["steps"][0]

    assert entry["on_failure"] == "abort"


def test_no_engine_is_targeted_before_phase_sixteen() -> None:
    payload = plan_payload(run(), REQUEST, SCOPE)

    assert payload["target_engine_id"] is None
    assert payload["target_model_id"] == "qwen2.5-coder:7b"
