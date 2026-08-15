from __future__ import annotations

import pytest

from project_service.lifecycle import IllegalTransitionError, assert_transition, can_transition


def test_draft_may_activate_or_archive() -> None:
    assert can_transition("draft", "active")
    assert can_transition("draft", "archived")
    assert not can_transition("draft", "paused")


def test_active_and_paused_are_reversible() -> None:
    assert can_transition("active", "paused")
    assert can_transition("paused", "active")


def test_archived_is_terminal() -> None:
    for target in ("draft", "active", "paused", "archived"):
        assert not can_transition("archived", target)


def test_illegal_transition_names_the_allowed_targets() -> None:
    with pytest.raises(IllegalTransitionError) as error:
        assert_transition("draft", "paused")

    assert "active" in str(error.value)
    assert "archived" in str(error.value)
