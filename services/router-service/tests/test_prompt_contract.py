from __future__ import annotations

import re

import pytest
from bison_contracts import load_prompt

from router_service.actions import DECLARABLE_TYPES
from router_service.config import settings
from router_service.plan import FAILURE_POLICIES, INTENTS, SERVICES

TOP_LEVEL_KEYS = ("intent", "rationale", "steps")

STEP_KEYS = (
    "description",
    "service",
    "action",
    "effects",
    "on_failure",
    "criterion_refs",
)

EFFECT_KEYS = (
    "writes_paths",
    "deletes_paths",
    "network",
    "installs_packages",
    "needs_credentials",
    "drives_input",
    "reversible",
)

ACTION_FIELDS = (
    "path",
    "content",
    "script_path",
    "module",
    "arguments",
    "packages",
)


def prompt_text() -> str:
    resolved = settings()
    raw = load_prompt(resolved.prompt_name, resolved.prompt_version).text

    return re.sub(r"\s+", " ", raw)


@pytest.mark.parametrize("key", TOP_LEVEL_KEYS)
def test_the_prompt_names_every_top_level_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("key", STEP_KEYS)
def test_the_prompt_names_every_step_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("key", EFFECT_KEYS)
def test_the_prompt_names_every_effect_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("intent", sorted(INTENTS))
def test_the_prompt_lists_every_intent(intent: str) -> None:
    assert intent in prompt_text()


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_the_prompt_lists_every_service(service: str) -> None:
    assert service in prompt_text()


@pytest.mark.parametrize("policy", sorted(FAILURE_POLICIES))
def test_the_prompt_lists_every_failure_policy(policy: str) -> None:
    assert policy in prompt_text()


@pytest.mark.parametrize("action_type", sorted(DECLARABLE_TYPES))
def test_the_prompt_lists_every_action_type(action_type: str) -> None:
    assert action_type in prompt_text()


@pytest.mark.parametrize("field", ACTION_FIELDS)
def test_the_prompt_names_every_action_field(field: str) -> None:
    assert field in prompt_text()


def test_the_prompt_says_an_action_may_be_null() -> None:
    assert "null" in prompt_text()


def test_the_prompt_names_the_service_that_requires_an_action() -> None:
    text = prompt_text()

    assert "task-runner step" in text


def test_the_prompt_forbids_command_lines() -> None:
    text = prompt_text()

    assert "never carries a command line" in text


def test_the_prompt_requires_a_written_path_to_be_declared() -> None:
    assert "appears in writes_paths as well" in prompt_text()


def test_the_service_is_configured_with_a_prompt_that_knows_about_actions() -> None:
    resolved = settings()

    assert resolved.prompt_name == "router"
    assert "action" in load_prompt(resolved.prompt_name, resolved.prompt_version).text
