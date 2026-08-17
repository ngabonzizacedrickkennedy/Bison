from __future__ import annotations

from typing import Final

TERMINAL_STATES: Final[frozenset[str]] = frozenset({"succeeded", "aborted"})

TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"awaiting_confirmation", "running", "aborted"}),
    "awaiting_confirmation": frozenset({"running", "aborted"}),
    "running": frozenset({"succeeded", "failed", "aborted"}),
    "failed": frozenset({"running", "aborted"}),
    "succeeded": frozenset(),
    "aborted": frozenset(),
}

REASON_REQUIRED: Final[frozenset[str]] = frozenset({"failed", "aborted"})

RECONCILIATION_ONLY_STATES: Final[frozenset[str]] = frozenset({"never_attempted"})


class IllegalStepTransitionError(RuntimeError):
    def __init__(self, current: str, target: str) -> None:
        allowed = ", ".join(sorted(TRANSITIONS.get(current, frozenset()))) or "nothing"
        super().__init__(
            f"step in state {current} cannot move to {target}; allowed from here: {allowed}"
        )
        self.current = current
        self.target = target


class StepReasonRequiredError(RuntimeError):
    def __init__(self, target: str) -> None:
        super().__init__(f"moving a step to {target} requires a reason")
        self.target = target


class ReconciliationOnlyStateError(RuntimeError):
    def __init__(self, target: str) -> None:
        super().__init__(
            f"{target} is reconciliation vocabulary and is never written as a step transition"
        )
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str, reason: str | None) -> None:
    if target in RECONCILIATION_ONLY_STATES:
        raise ReconciliationOnlyStateError(target)

    if not can_transition(current, target):
        raise IllegalStepTransitionError(current, target)

    if target in REASON_REQUIRED and not reason:
        raise StepReasonRequiredError(target)
