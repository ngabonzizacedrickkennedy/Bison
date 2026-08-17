from __future__ import annotations

import pytest

from project_service.reconcile import (
    CriterionState,
    PlannedStep,
    RecordedOutcome,
    UnknownHaltReasonError,
    UnknownStepStateError,
    UnplannedStepError,
    partition,
    reconcile,
    settle,
    summarise,
    touched,
)


def steps(count: int = 5) -> list[PlannedStep]:
    return [
        PlannedStep(step_id=f"s{index}", position=index, description=f"step {index}")
        for index in range(count)
    ]


def outcome(
    step_id: str,
    state: str,
    touched_paths: list[str] | None = None,
    exit_code: int | None = None,
    error_message: str | None = None,
) -> RecordedOutcome:
    return RecordedOutcome(
        step_id=step_id,
        state=state,
        touched_paths=touched_paths or [],
        exit_code=exit_code,
        error_message=error_message,
        started_at="2026-08-17T09:00:00+00:00",
        ended_at="2026-08-17T09:00:01+00:00",
    )


def test_unrecorded_steps_are_reported_as_never_attempted() -> None:
    settled = settle(steps(), [outcome("s0", "succeeded"), outcome("s1", "succeeded")])

    assert len(settled) == 5
    assert [s.state for s in settled] == [
        "succeeded",
        "succeeded",
        "never_attempted",
        "never_attempted",
        "never_attempted",
    ]


def test_a_step_in_flight_settles_to_aborted() -> None:
    settled = settle(steps(3), [outcome("s0", "succeeded"), outcome("s1", "running")])

    assert settled[1].state == "aborted"


def test_a_step_awaiting_confirmation_settles_to_never_attempted() -> None:
    settled = settle(steps(2), [outcome("s1", "awaiting_confirmation")])

    assert settled[1].state == "never_attempted"


def test_outcomes_are_ordered_by_position_not_arrival() -> None:
    settled = settle(steps(3), [outcome("s2", "succeeded"), outcome("s0", "succeeded")])

    assert [s.step_id for s in settled] == ["s0", "s1", "s2"]
    assert [s.position for s in settled] == [0, 1, 2]


def test_a_retried_step_keeps_its_last_outcome() -> None:
    settled = settle(
        steps(1),
        [outcome("s0", "failed", error_message="first"), outcome("s0", "succeeded")],
    )

    assert settled[0].state == "succeeded"
    assert settled[0].error_message is None


def test_an_outcome_for_an_unplanned_step_raises() -> None:
    with pytest.raises(UnplannedStepError) as raised:
        settle(steps(2), [outcome("s0", "succeeded"), outcome("ghost", "succeeded")])

    assert raised.value.missing == ["ghost"]


def test_an_unknown_step_state_raises() -> None:
    with pytest.raises(UnknownStepStateError):
        settle(steps(1), [outcome("s0", "finished")])


def test_an_unknown_halt_reason_raises() -> None:
    with pytest.raises(UnknownHaltReasonError):
        reconcile("r", "t", "gave_up", steps(1), [], [], 0.0)


def test_ignored_criteria_appear_in_neither_list() -> None:
    verified, unverified = partition(
        [
            CriterionState(id="c1", status="verified"),
            CriterionState(id="c2", status="unverified"),
            CriterionState(id="c3", status="ignored"),
            CriterionState(id="c4", status="failed"),
        ]
    )

    assert verified == ["c1"]
    assert unverified == ["c2", "c4"]


def test_touched_paths_are_distinct_and_keep_first_seen_order() -> None:
    settled = settle(
        steps(3),
        [
            outcome("s0", "succeeded", ["b.txt", "a.txt"]),
            outcome("s1", "failed", ["a.txt", "c.txt"]),
        ],
    )

    assert touched(settled) == ["b.txt", "a.txt", "c.txt"]


def test_summary_names_the_failed_step_and_the_verified_percentage() -> None:
    settled = settle(
        steps(9),
        [
            outcome("s0", "succeeded", ["one.txt"]),
            outcome("s1", "succeeded", ["two.txt"]),
            outcome("s2", "succeeded"),
            outcome("s3", "failed", error_message="permission denied"),
        ],
    )

    summary = summarise("step_failure", settled, touched(settled), 40.0)

    assert summary == (
        "3 of 9 steps completed. Step 4 failed: step 3. 5 steps never attempted. "
        "2 files touched. Task is 40% verified. Halted by step failure."
    )


def test_summary_states_plainly_when_nothing_was_touched() -> None:
    settled = settle(steps(1), [outcome("s0", "running")])

    summary = summarise("kill_switch", settled, touched(settled), 0.0)

    assert summary == (
        "0 of 1 step completed. 1 step stopped in flight. "
        "No files were touched. Task is 0% verified. Halted by kill switch."
    )


def test_a_fractional_percentage_survives_into_the_summary() -> None:
    settled = settle(steps(1), [outcome("s0", "succeeded")])

    assert "Task is 66.7% verified." in summarise("user_stop", settled, [], 66.666)


def test_reconcile_counts_agree_with_the_outcomes_it_carries() -> None:
    record = reconcile(
        request_id="req",
        task_id="task",
        halt_reason="kill_switch",
        steps=steps(5),
        outcomes=[
            outcome("s0", "succeeded", ["a.txt"]),
            outcome("s1", "succeeded"),
            outcome("s2", "running", ["b.txt"]),
        ],
        criteria=[
            CriterionState(id="c1", status="verified"),
            CriterionState(id="c2", status="unverified"),
            CriterionState(id="c3", status="ignored"),
        ],
        percentage=50.0,
    )

    assert record.steps_total == 5
    assert record.steps_completed == 2
    assert record.steps_never_attempted == 2
    assert len(record.step_outcomes) == record.steps_total
    assert record.criteria_verified_ids == ["c1"]
    assert record.criteria_unverified_ids == ["c2"]
    assert record.touched_paths == ["a.txt", "b.txt"]
    assert record.plain_summary.startswith("2 of 5 steps completed.")
