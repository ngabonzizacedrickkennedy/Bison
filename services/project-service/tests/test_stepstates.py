from __future__ import annotations

import pytest

from project_service.stepstates import (
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalStepTransitionError,
    ReconciliationOnlyStateError,
    StepReasonRequiredError,
    assert_transition,
    can_transition,
)


def test_a_pending_step_can_be_gated_run_or_aborted() -> None:
    assert can_transition("pending", "awaiting_confirmation")
    assert can_transition("pending", "running")
    assert can_transition("pending", "aborted")


def test_a_pending_step_cannot_succeed_without_running() -> None:
    with pytest.raises(IllegalStepTransitionError) as raised:
        assert_transition("pending", "succeeded", None)

    assert raised.value.current == "pending"
    assert "awaiting_confirmation" in str(raised.value)


def test_a_gated_step_cannot_skip_its_confirmation() -> None:
    assert can_transition("awaiting_confirmation", "running")
    assert not can_transition("awaiting_confirmation", "succeeded")


def test_a_failed_step_may_retry_but_a_succeeded_one_may_not() -> None:
    assert can_transition("failed", "running")
    assert not can_transition("succeeded", "running")


def test_terminal_states_lead_nowhere() -> None:
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset()


def test_failing_or_aborting_demands_a_reason() -> None:
    with pytest.raises(StepReasonRequiredError):
        assert_transition("running", "failed", None)

    with pytest.raises(StepReasonRequiredError):
        assert_transition("running", "aborted", "")

    assert_transition("running", "aborted", "halted by kill switch")


def test_succeeding_needs_no_reason() -> None:
    assert_transition("running", "succeeded", None)


def test_never_attempted_is_reconciliation_vocabulary_only() -> None:
    with pytest.raises(ReconciliationOnlyStateError):
        assert_transition("pending", "never_attempted", "halted")


def test_an_unknown_state_has_no_exits() -> None:
    assert not can_transition("marinating", "running")
