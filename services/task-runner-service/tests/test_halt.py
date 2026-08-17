from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bison_contracts.halt import HaltedError, HaltSignal, HaltState


def signal(reason: str = "kill_switch", identifier: str = "h1") -> HaltSignal:
    return HaltSignal(
        id=identifier,
        reason=reason,  # type: ignore[arg-type]
        request_id="8d29d364-21ff-401b-ad80-24b0723985c6",
        project_id="b18c40f1-c35e-497e-8ebf-dbf413f472d7",
        task_id="19427f55-dd12-4ef4-940a-b69270de80bd",
        issued_at=datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
    )


def runner() -> HaltState:
    return HaltState("task-runner-service", "immediate")


def test_a_fresh_service_accepts_work() -> None:
    state = runner()

    state.guard()

    assert state.halted is False
    assert state.signal is None


def test_accepting_a_signal_halts_and_reports_the_boundary() -> None:
    state = runner()

    acknowledgement = state.accept(signal())

    assert state.halted is True
    assert acknowledgement.boundary == "immediate"
    assert acknowledgement.boundary_meaning == "the process tree is killed without waiting"
    assert acknowledgement.already_halted is False
    assert acknowledgement.signals_received == 1


def test_a_halted_service_refuses_new_work_and_names_the_signal() -> None:
    state = runner()
    state.accept(signal(reason="user_stop"))

    with pytest.raises(HaltedError) as raised:
        state.guard()

    assert raised.value.service == "task-runner-service"
    assert raised.value.signal.reason == "user_stop"


def test_repeated_signals_do_not_reset_the_first_halt() -> None:
    state = runner()

    first = state.accept(signal(identifier="h1"))
    second = state.accept(signal(identifier="h2", reason="user_stop"))

    assert first.already_halted is False
    assert second.already_halted is True
    assert second.signals_received == 2
    assert state.status().halted_at == first.accepted_at
    assert state.signal is not None
    assert state.signal.id == "h2"


def test_nothing_but_resume_clears_a_halt() -> None:
    state = runner()
    state.accept(signal())

    with pytest.raises(HaltedError):
        state.guard()

    with pytest.raises(HaltedError):
        state.guard()

    assert state.halted is True


def test_resume_records_who_cleared_it_and_keeps_the_signal_history() -> None:
    state = runner()
    state.accept(signal())

    status = state.resume("user")

    assert status.halted is False
    assert status.resumed_by == "user"
    assert status.resumed_at is not None
    assert status.signals_received == 1
    assert status.signal is not None

    state.guard()


def test_halting_after_a_resume_starts_a_new_halt_window() -> None:
    state = runner()
    state.accept(signal(identifier="h1"))
    state.resume("user")

    acknowledgement = state.accept(signal(identifier="h2"))
    status = state.status()

    assert acknowledgement.already_halted is False
    assert status.resumed_at is None
    assert status.resumed_by is None
    assert status.halted_at == acknowledgement.accepted_at


def test_each_service_declares_its_own_boundary() -> None:
    automation = HaltState("automation-service", "between_actions")
    mediator = HaltState("mediator-service", "between_tasks")

    assert automation.accept(signal()).boundary_meaning == (
        "the action in flight completes, then nothing further starts"
    )
    assert mediator.accept(signal()).boundary_meaning == (
        "the task in flight completes, then nothing further starts"
    )
