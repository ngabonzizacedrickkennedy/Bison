from __future__ import annotations

import dataclasses
from typing import Any

from router_service.actions import InstallPythonPackages, RunPythonModule, WriteFile
from router_service.api import StepRead, step_read
from router_service.gating import GatedStep
from router_service.plan import Effects

SCOPE = r"C:\Users\x\bison\projects\demo"

TARGET = SCOPE + r"\reconcile.py"


def effects(**overrides: Any) -> Effects:
    declared: dict[str, Any] = {
        "writes_paths": [],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    declared.update(overrides)

    return Effects(**declared)


def gated(**overrides: Any) -> GatedStep:
    declared: dict[str, Any] = {
        "position": 0,
        "description": "Write the reconciliation module",
        "service": "task-runner",
        "action": WriteFile(path=TARGET, content="print(1)\n"),
        "requires_confirmation": False,
        "confirmation_reason": None,
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": ["c1"],
        "effects": effects(writes_paths=[TARGET]),
    }
    declared.update(overrides)

    return GatedStep(**declared)


def test_the_response_carries_every_field_the_gated_step_holds() -> None:
    declared = {field.name for field in dataclasses.fields(GatedStep)}
    returned = set(StepRead.model_fields)

    assert declared <= returned


def test_a_written_action_reaches_the_caller() -> None:
    read = step_read(gated(), "s-1")

    assert read.action is not None
    assert read.action["type"] == "write_file"
    assert read.action["path"] == TARGET


def test_the_content_a_caller_must_write_survives_the_response() -> None:
    body = "import os\n\n\nprint(len(os.listdir('.')))\n"
    read = step_read(gated(action=WriteFile(path=TARGET, content=body)), "s-1")

    assert read.action is not None
    assert read.action["content"] == body


def test_a_module_action_reaches_the_caller_with_its_arguments() -> None:
    action = RunPythonModule(module="pytest", arguments=("-q", "tests"))
    read = step_read(gated(action=action), "s-1")

    assert read.action is not None
    assert read.action["module"] == "pytest"
    assert read.action["arguments"] == ["-q", "tests"]


def test_an_install_action_reaches_the_caller_with_its_packages() -> None:
    action = InstallPythonPackages(packages=("fastapi", "uvicorn"))
    read = step_read(gated(action=action), "s-1")

    assert read.action is not None
    assert read.action["packages"] == ["fastapi", "uvicorn"]


def test_a_step_for_another_service_reports_null_rather_than_omitting_it() -> None:
    read = step_read(gated(service="automation", action=None), "s-1")

    assert read.action is None
    assert "action" in read.model_dump()


def test_the_response_names_the_stored_step_rather_than_its_position() -> None:
    read = step_read(gated(position=3), "step-abc")

    assert read.step_id == "step-abc"
    assert read.position == 3


def test_a_gated_step_carries_its_reason_to_the_caller() -> None:
    read = step_read(
        gated(requires_confirmation=True, confirmation_reason="installs packages"), "s-1"
    )

    assert read.requires_confirmation is True
    assert read.confirmation_reason == "installs packages"


def test_the_effects_the_gate_judged_are_the_effects_reported() -> None:
    read = step_read(gated(effects=effects(writes_paths=[TARGET], network=True)), "s-1")

    assert read.effects.writes_paths == [TARGET]
    assert read.effects.network is True


def test_an_action_reaches_the_wire_and_not_only_the_model() -> None:
    stored: Any = step_read(gated(), "s-1").model_dump(mode="json")["action"]

    assert stored["type"] == "write_file"
    assert stored["content"] == "print(1)\n"
