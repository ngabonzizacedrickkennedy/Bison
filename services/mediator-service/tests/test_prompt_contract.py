from __future__ import annotations

import re

import pytest
from bison_contracts import load_prompt

from mediator_service.checks import DECLARABLE_TYPES, REFUSED_TYPES
from mediator_service.config import settings
from mediator_service.tree import ASSIGNED_ROLES, CHECK_KINDS, TASK_KINDS

TASK_KEYS = (
    "ref",
    "parent_ref",
    "title",
    "description",
    "kind",
    "assigned_role",
    "depends_on",
    "criteria",
)

CRITERION_KEYS = ("statement", "check_kind", "check_spec", "weight")

TOP_LEVEL_KEYS = ("approach_summary", "tasks")


def prompt_text() -> str:
    resolved = settings()
    raw = load_prompt(resolved.mediator_prompt_name, resolved.mediator_prompt_version).text

    return re.sub(r"\s+", " ", raw)


@pytest.mark.parametrize("key", TOP_LEVEL_KEYS)
def test_the_prompt_names_every_top_level_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("key", TASK_KEYS)
def test_the_prompt_names_every_task_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("key", CRITERION_KEYS)
def test_the_prompt_names_every_criterion_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("kind", sorted(TASK_KINDS))
def test_the_prompt_lists_every_task_kind(kind: str) -> None:
    assert kind in prompt_text()


@pytest.mark.parametrize("role", sorted(ASSIGNED_ROLES))
def test_the_prompt_lists_every_assigned_role(role: str) -> None:
    assert role in prompt_text()


@pytest.mark.parametrize("check_kind", sorted(CHECK_KINDS))
def test_the_prompt_lists_every_check_kind(check_kind: str) -> None:
    assert check_kind in prompt_text()


@pytest.mark.parametrize("check_type", sorted(DECLARABLE_TYPES))
def test_the_prompt_shows_every_check_type_the_parser_accepts(check_type: str) -> None:
    assert check_type in prompt_text()


@pytest.mark.parametrize("check_type", sorted(REFUSED_TYPES))
def test_the_prompt_does_not_offer_a_check_type_the_parser_refuses(
    check_type: str,
) -> None:
    text = prompt_text()

    assert f'"type": "{check_type}"' not in text


def test_the_prompt_says_criteria_belong_on_leaves() -> None:
    assert "leaves" in prompt_text()


def test_the_prompt_forbids_depending_on_a_parent_or_child() -> None:
    text = prompt_text()

    assert "parent" in text
    assert "child" in text


def test_the_prompt_asks_for_one_claim_per_criterion() -> None:
    assert "one thing per criterion" in prompt_text()


def test_the_engine_prompt_asks_for_prose_rather_than_json() -> None:
    resolved = settings()
    text = load_prompt(resolved.engine_prompt_name, resolved.engine_prompt_version).text

    assert text.strip()
