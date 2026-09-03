from __future__ import annotations

import json
from typing import Any

import pytest

from mediator_service.events import (
    TERMINAL_EVENTS,
    Emitter,
    criterion_settled,
    encode,
    error,
    halted,
    is_terminal,
    plan_ready,
    run_finished,
    run_started,
    step_awaiting_confirmation,
    step_finished,
    step_output,
    step_started,
    task_finished,
    task_replanning,
    task_started,
)


def emitter() -> Emitter:
    return Emitter("req-1", "proj-1")


def decode(line: bytes) -> dict[str, Any]:
    parsed: Any = json.loads(line.decode("utf-8"))

    assert isinstance(parsed, dict)

    return parsed


def every_event() -> list[dict[str, Any]]:
    return [
        run_started(("a", "b")),
        task_started("t-1", "Set up", 0, 2),
        plan_ready("t-1", "p-1", 3, 1),
        step_awaiting_confirmation("t-1", "s-1", 0, "Install", "installs packages"),
        step_started("t-1", "s-1", 0, "Install"),
        step_output("t-1", "s-1", "stdout", 0, "working"),
        step_finished("t-1", "s-1", "succeeded", 0, None, None),
        task_replanning("t-1", "p-1", 1, 2, "the step exited with code 1"),
        criterion_settled("t-1", "c-1", "File exists", "verified", "found"),
        task_finished("t-1", "done", None, 100.0, 50.0),
        halted("kill_switch", "t-1", "r-1"),
        run_finished(1, 0, 2, 50.0),
        error("something broke"),
    ]


def test_every_constructor_names_its_event_type() -> None:
    for event in every_event():
        assert isinstance(event.get("event"), str)
        assert event["event"]


def test_run_started_counts_the_tasks_it_was_given() -> None:
    event = run_started(("a", "b", "c"))

    assert event["order"] == ["a", "b", "c"]
    assert event["tasks_total"] == 3


def test_run_started_copies_the_order_rather_than_holding_the_tuple() -> None:
    order = ("a", "b")
    event = run_started(order)

    assert event["order"] == list(order)
    assert event["order"] is not order


def test_a_terminal_event_is_recognised() -> None:
    assert is_terminal(run_finished(1, 0, 1, 100.0))
    assert is_terminal(halted("user_stop", None, None))
    assert is_terminal(error("broke"))


def test_a_mid_run_event_is_not_terminal() -> None:
    assert not is_terminal(task_started("t-1", "Set up", 0, 1))
    assert not is_terminal(step_output("t-1", "s-1", "stdout", 0, "hi"))
    assert not is_terminal(task_finished("t-1", "done", None, 100.0, 50.0))


def test_a_replan_does_not_end_the_run() -> None:
    assert not is_terminal(task_replanning("t-1", "p-1", 1, 2, "the step failed"))


def test_a_task_finishing_is_not_the_run_finishing() -> None:
    assert "task_finished" not in TERMINAL_EVENTS


def test_an_unknown_shape_is_not_terminal() -> None:
    assert not is_terminal({})


def test_the_stamp_carries_the_run_identity() -> None:
    stamped = emitter().stamp(task_started("t-1", "Set up", 0, 1))

    assert stamped["request_id"] == "req-1"
    assert stamped["project_id"] == "proj-1"


def test_the_first_event_is_sequence_zero() -> None:
    assert emitter().stamp(run_started(("a",)))["sequence"] == 0


def test_one_counter_runs_across_every_kind_of_event() -> None:
    active = emitter()
    stamped = [active.stamp(event) for event in every_event()]

    assert [event["sequence"] for event in stamped] == list(range(len(stamped)))


def test_the_counter_advances_even_when_the_same_event_repeats() -> None:
    active = emitter()
    first = active.stamp(step_output("t-1", "s-1", "stdout", 0, "a"))
    second = active.stamp(step_output("t-1", "s-1", "stdout", 1, "b"))

    assert first["sequence"] == 0
    assert second["sequence"] == 1


def test_a_step_keeps_its_own_counter_alongside_the_run_counter() -> None:
    active = emitter()
    active.stamp(run_started(("t-1",)))
    stamped = active.stamp(step_output("t-1", "s-1", "stdout", 0, "a"))

    assert stamped["sequence"] == 1
    assert stamped["step_sequence"] == 0


def test_an_event_cannot_forge_its_own_provenance() -> None:
    forged = {
        "event": "task_started",
        "request_id": "someone-else",
        "project_id": "another-project",
        "sequence": 999,
    }
    stamped = emitter().stamp(forged)

    assert stamped["request_id"] == "req-1"
    assert stamped["project_id"] == "proj-1"
    assert stamped["sequence"] == 0


def test_the_stamp_does_not_mutate_what_it_was_given() -> None:
    event = task_started("t-1", "Set up", 0, 1)
    emitter().stamp(event)

    assert "sequence" not in event
    assert "request_id" not in event


def test_two_runs_count_independently() -> None:
    first = Emitter("req-1", "proj-1")
    second = Emitter("req-2", "proj-2")

    first.stamp(run_started(("a",)))
    first.stamp(run_started(("a",)))
    stamped = second.stamp(run_started(("a",)))

    assert stamped["sequence"] == 0
    assert first.sequence == 2
    assert second.sequence == 1


def test_the_counter_is_readable_before_anything_is_emitted() -> None:
    assert emitter().sequence == 0


def test_encoding_produces_exactly_one_line() -> None:
    line = encode(run_started(("a",)))

    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1


def test_encoding_leaves_no_space_between_fields() -> None:
    assert b", " not in encode(task_started("t-1", "Set up", 0, 1))


def test_every_event_survives_a_round_trip() -> None:
    active = emitter()

    for event in every_event():
        assert decode(active.emit(event)) == active.stamp(event) | {"sequence": active.sequence - 2}


def test_text_outside_ascii_survives_the_wire() -> None:
    awkward = f"end{chr(0x2011)}to{chr(0x2011)}end"
    decoded = decode(emitter().emit(step_output("t-1", "s-1", "stdout", 0, awkward)))

    assert decoded["text"] == awkward


def test_emitting_advances_the_counter() -> None:
    active = emitter()
    first = decode(active.emit(run_started(("a",))))
    second = decode(active.emit(task_started("t-1", "Set up", 0, 1)))

    assert first["sequence"] == 0
    assert second["sequence"] == 1


def test_an_absent_value_is_reported_as_null_rather_than_dropped() -> None:
    decoded = decode(emitter().emit(step_finished("t-1", "s-1", "aborted", None, "halt", None)))

    assert decoded["exit_code"] is None
    assert decoded["error_message"] is None
    assert decoded["terminated_by"] == "halt"


def test_a_halt_with_nothing_in_flight_still_reports_its_reason() -> None:
    decoded = decode(emitter().emit(halted("user_stop", None, None)))

    assert decoded["reason"] == "user_stop"
    assert decoded["task_id"] is None
    assert decoded["record_id"] is None


def test_an_error_outside_any_task_carries_no_task() -> None:
    assert error("broker unreachable")["task_id"] is None


def test_percentages_are_carried_and_not_recomputed() -> None:
    event = task_finished("t-1", "done", None, 66.7, 41.2)

    assert event["task_percentage"] == pytest.approx(66.7)
    assert event["project_percentage"] == pytest.approx(41.2)


def test_a_skipped_task_carries_the_reason_it_was_skipped() -> None:
    event = task_finished("t-1", "skipped", "no database on this machine", 0.0, 12.5)

    assert event["state"] == "skipped"
    assert event["reason"] == "no database on this machine"


def test_a_confirmation_gate_names_the_step_and_the_reason() -> None:
    event = step_awaiting_confirmation("t-1", "s-2", 1, "Delete build output", "deletes files")

    assert event["step_id"] == "s-2"
    assert event["position"] == 1
    assert event["reason"] == "deletes files"


def test_a_plan_reports_how_many_of_its_steps_are_gated() -> None:
    event = plan_ready("t-1", "p-1", 5, 2)

    assert event["steps_total"] == 5
    assert event["gated_total"] == 2


def test_a_replan_names_the_plan_it_abandons_not_the_one_it_will_build() -> None:
    event = task_replanning("t-1", "p-1", 1, 2, "the step exited with code 1")

    assert event["superseded_plan_id"] == "p-1"
    assert "plan_id" not in event


def test_a_replan_reports_the_attempt_against_its_bound() -> None:
    event = task_replanning("t-1", "p-1", 2, 2, "the step exited with code 1")

    assert event["attempt"] == 2
    assert event["attempts_allowed"] == 2


def test_a_replan_carries_the_failure_that_caused_it() -> None:
    event = task_replanning("t-1", "p-3", 1, 2, "no python interpreter on PATH")

    assert event["reason"] == "no python interpreter on PATH"


def test_a_finished_run_accounts_for_every_task() -> None:
    event = run_finished(3, 1, 5, 60.0)

    assert event["tasks_completed"] + event["tasks_failed"] <= event["tasks_total"]
