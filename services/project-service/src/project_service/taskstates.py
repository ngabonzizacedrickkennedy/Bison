from __future__ import annotations

from typing import Final

TERMINAL_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "skipped", "ignored"})

TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"ready", "skipped", "ignored"}),
    "ready": frozenset({"in_progress", "blocked", "skipped", "ignored"}),
    "in_progress": frozenset(
        {
            "blocked",
            "awaiting_confirmation",
            "awaiting_clarification",
            "verifying",
            "failed",
            "skipped",
            "ignored",
        }
    ),
    "blocked": frozenset({"ready", "in_progress", "failed", "skipped", "ignored"}),
    "awaiting_confirmation": frozenset({"in_progress", "failed", "skipped", "ignored"}),
    "awaiting_clarification": frozenset({"in_progress", "failed", "skipped", "ignored"}),
    "verifying": frozenset({"done", "failed", "blocked", "skipped", "ignored"}),
    "done": frozenset({"ready"}),
    "failed": frozenset({"ready", "skipped", "ignored"}),
    "skipped": frozenset({"pending", "ready"}),
    "ignored": frozenset({"pending", "ready"}),
}

REASON_REQUIRED: Final[frozenset[str]] = frozenset({"skipped", "ignored", "blocked", "failed"})


class IllegalTaskTransitionError(RuntimeError):
    def __init__(self, current: str, target: str) -> None:
        allowed = ", ".join(sorted(TRANSITIONS.get(current, frozenset()))) or "nothing"
        super().__init__(
            f"task in state {current} cannot move to {target}; allowed from here: {allowed}"
        )
        self.current = current
        self.target = target


class ReasonRequiredError(RuntimeError):
    def __init__(self, target: str) -> None:
        super().__init__(f"moving a task to {target} requires a reason")
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str, reason: str | None) -> None:
    if not can_transition(current, target):
        raise IllegalTaskTransitionError(current, target)

    if target in REASON_REQUIRED and not reason:
        raise ReasonRequiredError(target)
