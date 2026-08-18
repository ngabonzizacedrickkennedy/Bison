from __future__ import annotations

from typing import Any

import pytest

from task_runner_service.scope import (
    ScopeRootError,
    StepRefusedError,
    assert_admissible,
    assess,
)

ROOT = r"C:\Users\x\bison"


def step(**effects: Any) -> dict[str, Any]:
    declared: dict[str, Any] = {
        "writes_paths": [],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    declared.update(effects)

    return {"service": "task-runner", "effects": declared}


def test_a_contained_reversible_step_needs_no_confirmation() -> None:
    verdict = assess(step(writes_paths=[r"out\report.csv"]), ROOT, confirmed=False)

    assert verdict.admissible
    assert verdict.refusals == []
    assert verdict.requirements == []


def test_absolute_paths_inside_the_root_are_contained() -> None:
    verdict = assess(step(writes_paths=[r"C:\Users\x\bison\out\report.csv"]), ROOT, confirmed=False)

    assert verdict.admissible


def test_containment_ignores_case() -> None:
    verdict = assess(step(writes_paths=[r"C:\USERS\X\BISON\out.txt"]), ROOT, confirmed=False)

    assert verdict.admissible


def test_a_sibling_directory_sharing_a_prefix_is_not_contained() -> None:
    verdict = assess(step(writes_paths=[r"C:\Users\x\bisonx\out.txt"]), ROOT, confirmed=False)

    assert not verdict.admissible
    assert verdict.refusals


def test_a_write_outside_the_root_is_refused_even_when_confirmed() -> None:
    verdict = assess(step(writes_paths=[r"C:\Windows\System32\drivers\etc\hosts"]), ROOT, True)

    assert not verdict.admissible
    assert "outside the project directory" in verdict.refusals[0]


def test_traversal_out_of_the_root_is_refused() -> None:
    verdict = assess(step(deletes_paths=[r"..\..\secrets"]), ROOT, confirmed=True)

    assert not verdict.admissible
    assert any("deletes" in entry for entry in verdict.refusals)


def test_an_environment_variable_reference_is_refused_rather_than_resolved() -> None:
    verdict = assess(step(writes_paths=[r"%USERPROFILE%\.ssh\id_rsa"]), ROOT, confirmed=True)

    assert not verdict.admissible


def test_a_drive_relative_path_is_refused() -> None:
    verdict = assess(step(writes_paths=["C:report.csv"]), ROOT, confirmed=True)

    assert not verdict.admissible


def test_escaped_paths_are_named_and_counted() -> None:
    outside = [rf"D:\loose\{index}.txt" for index in range(5)]
    verdict = assess(step(writes_paths=outside), ROOT, confirmed=False)

    assert "and 2 more" in verdict.refusals[0]


def test_a_step_routed_elsewhere_is_refused() -> None:
    payload = step()
    payload["service"] = "automation"

    verdict = assess(payload, ROOT, confirmed=True)

    assert not verdict.admissible
    assert "not task-runner" in verdict.refusals[0]


def test_a_missing_effects_block_is_refused() -> None:
    verdict = assess({"service": "task-runner"}, ROOT, confirmed=True)

    assert not verdict.admissible
    assert "declares no effects block" in verdict.refusals


def test_an_empty_effects_block_fails_closed() -> None:
    verdict = assess({"service": "task-runner", "effects": {}}, ROOT, confirmed=False)

    assert not verdict.admissible
    assert verdict.refusals
    assert "reaches the network" in verdict.requirements
    assert "installs packages" in verdict.requirements


def test_malformed_path_declarations_are_refused() -> None:
    verdict = assess(step(writes_paths="out.txt", deletes_paths=[7]), ROOT, confirmed=True)

    assert "declares a malformed writes_paths" in verdict.refusals
    assert "declares a malformed deletes_paths" in verdict.refusals


def test_driving_input_is_refused_and_confirmation_does_not_clear_it() -> None:
    verdict = assess(step(drives_input=True), ROOT, confirmed=True)

    assert not verdict.admissible
    assert any("moves the mouse" in entry for entry in verdict.refusals)


def test_deleting_inside_the_root_requires_confirmation() -> None:
    payload = step(deletes_paths=[r"out\stale.csv"], reversible=False)

    assert not assess(payload, ROOT, confirmed=False).admissible
    assert assess(payload, ROOT, confirmed=True).admissible


def test_network_installs_and_credentials_are_requirements_not_refusals() -> None:
    payload = step(network=True, installs_packages=True, needs_credentials=True)
    verdict = assess(payload, ROOT, confirmed=False)

    assert verdict.refusals == []
    assert len(verdict.requirements) == 3
    assert assess(payload, ROOT, confirmed=True).admissible


def test_an_irreversible_step_requires_confirmation() -> None:
    payload = step(reversible=False)

    assert not assess(payload, ROOT, confirmed=False).admissible
    assert assess(payload, ROOT, confirmed=True).admissible


def test_a_relative_scope_root_is_rejected() -> None:
    with pytest.raises(ScopeRootError):
        assess(step(), "bison", confirmed=False)


def test_assert_admissible_is_silent_when_the_step_is_admissible() -> None:
    assert_admissible(step(writes_paths=[r"out\report.csv"]), ROOT, confirmed=False)


def test_assert_admissible_reports_requirements_only_while_unconfirmed() -> None:
    payload = step(network=True)

    with pytest.raises(StepRefusedError) as unconfirmed:
        assert_admissible(payload, ROOT, confirmed=False)

    assert unconfirmed.value.requirements == ["reaches the network"]


def test_assert_admissible_reports_refusals_when_confirmed() -> None:
    payload = step(writes_paths=[r"D:\elsewhere\out.txt"], network=True)

    with pytest.raises(StepRefusedError) as refused:
        assert_admissible(payload, ROOT, confirmed=True)

    assert refused.value.refusals
    assert refused.value.requirements == []
