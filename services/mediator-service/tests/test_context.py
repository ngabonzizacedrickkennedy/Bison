from __future__ import annotations

from typing import Any

import pytest

from mediator_service.context import (
    MAX_CONTEXT_CHARS,
    TRUNCATION_NOTE,
    BriefFacts,
    Capability,
    MachineFacts,
    MediatorContext,
    render,
)


def machine() -> MachineFacts:
    return MachineFacts(
        os_version="Windows 11 26100",
        cpu_cores=8,
        ram_gb=16,
        free_disk_gb=214.5,
        capabilities=[
            Capability(name="sandbox", backend="job_object", strength="medium"),
            Capability(name="secrets", backend="keytar", strength="full"),
            Capability(name="input_injection", backend=None, strength="unavailable"),
        ],
    )


def brief(**overrides: Any) -> BriefFacts:
    base: dict[str, Any] = {
        "interpreted_goal": "Stand up a task tracker with a REST API",
        "project_type": "software",
        "summary": "The user wants a small tracker backed by SQLite",
        "known_constraints": ["No admin rights", "No GPU"],
        "assumptions": ["Python is available"],
        "out_of_scope": ["Mobile clients"],
        "seeded_success_criteria": ["The API answers on port 8000"],
    }
    base.update(overrides)

    return BriefFacts(**base)


def context(brief_overrides: dict[str, Any] | None = None) -> MediatorContext:
    return MediatorContext(
        brief=brief(**(brief_overrides or {})),
        machine=machine(),
        scope_root=r"C:\Users\cedrick.ngabonziza\bison-projects\tracker",
    )


def test_the_essential_facts_are_all_rendered() -> None:
    rendered = render(context())

    assert "Stand up a task tracker" in rendered
    assert "PROJECT TYPE: software" in rendered
    assert r"bison-projects\tracker" in rendered


def test_the_machine_is_rendered_with_its_backends() -> None:
    rendered = render(context())

    assert "sandbox: job_object (medium)" in rendered
    assert "cpu cores: 8" in rendered


def test_an_absent_backend_is_named_rather_than_left_blank() -> None:
    rendered = render(context())

    assert "input_injection: none (unavailable)" in rendered


def test_a_whole_number_of_gigabytes_is_not_padded() -> None:
    rendered = render(context())

    assert "ram: 16 GB" in rendered
    assert "free disk: 214.5 GB" in rendered


def test_the_user_s_own_success_criteria_are_carried_through() -> None:
    rendered = render(context())

    assert "SUCCESS CRITERIA THE USER ASKED FOR" in rendered
    assert "The API answers on port 8000" in rendered


def test_the_approach_is_absent_until_it_is_supplied() -> None:
    assert "PROPOSED APPROACH" not in render(context())


def test_the_approach_is_rendered_when_supplied() -> None:
    rendered = render(context(), MAX_CONTEXT_CHARS, "Build the schema first, then the routes")

    assert "PROPOSED APPROACH:" in rendered
    assert "Build the schema first" in rendered


def test_a_blank_approach_is_treated_as_absent() -> None:
    assert "PROPOSED APPROACH" not in render(context(), MAX_CONTEXT_CHARS, "   ")


def test_an_empty_list_leaves_out_its_heading() -> None:
    rendered = render(context({"assumptions": []}))

    assert "ASSUMPTIONS" not in rendered
    assert "CONSTRAINTS" in rendered


def test_a_blank_entry_is_not_rendered_as_a_bullet() -> None:
    rendered = render(context({"known_constraints": ["No admin rights", "   "]}))

    assert rendered.count("- No admin rights") == 1
    assert "- \n" not in rendered


def test_the_lists_degrade_together_before_anything_essential_goes() -> None:
    wide = context(
        {
            "known_constraints": [f"constraint {index}" for index in range(40)],
            "assumptions": [f"assumption {index}" for index in range(40)],
            "out_of_scope": [f"exclusion {index}" for index in range(40)],
            "seeded_success_criteria": [f"criterion {index}" for index in range(40)],
        }
    )
    rendered = render(wide, 1200)

    assert len(rendered) <= 1200
    assert "GOAL:" in rendered
    assert "MACHINE:" in rendered


def test_the_goal_survives_the_tightest_budget() -> None:
    rendered = render(context(), 400)

    assert "Stand up a task tracker" in rendered


def test_the_machine_survives_the_tightest_budget() -> None:
    rendered = render(context(), 400)

    assert "MACHINE:" in rendered
    assert "sandbox" in rendered


def test_the_summary_is_the_first_thing_dropped() -> None:
    full = render(context())
    squeezed = render(context(), 500)

    assert "SUMMARY:" in full
    assert "SUMMARY:" not in squeezed


@pytest.mark.parametrize("budget", [200, 500, 1200, 4000])
def test_a_tight_budget_is_actually_respected(budget: int) -> None:
    wide = context(
        {
            "interpreted_goal": "Stand up a tracker. " * 200,
            "summary": "Background. " * 400,
            "known_constraints": [f"constraint {index}" for index in range(60)],
        }
    )
    rendered = render(wide, budget)

    assert len(rendered) <= budget


def test_an_overlong_result_says_it_was_cut() -> None:
    wide = context({"interpreted_goal": "Stand up a tracker. " * 200})
    rendered = render(wide, 200)

    assert rendered.endswith(TRUNCATION_NOTE)


def test_an_overlong_approach_is_clipped_rather_than_dropped() -> None:
    rendered = render(context(), MAX_CONTEXT_CHARS, "step. " * 4000)

    assert "PROPOSED APPROACH:" in rendered
    assert TRUNCATION_NOTE in rendered


def test_the_same_context_renders_the_same_way_twice() -> None:
    assert render(context()) == render(context())
