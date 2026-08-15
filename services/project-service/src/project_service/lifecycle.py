from __future__ import annotations

from typing import Final, Literal

ProjectState = Literal["draft", "active", "paused", "archived"]

OPEN_STATES: Final[frozenset[str]] = frozenset({"draft", "active", "paused"})

TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"active", "archived"}),
    "active": frozenset({"paused", "archived"}),
    "paused": frozenset({"active", "archived"}),
    "archived": frozenset(),
}

EVENT_NAMES: Final[dict[str, str]] = {
    "active": "project.activated",
    "paused": "project.paused",
    "archived": "project.archived",
}


class IllegalTransitionError(RuntimeError):
    def __init__(self, current: str, target: str) -> None:
        allowed = ", ".join(sorted(TRANSITIONS.get(current, frozenset()))) or "nothing"
        super().__init__(
            f"project in state {current} cannot move to {target}; allowed from here: {allowed}"
        )
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise IllegalTransitionError(current, target)
