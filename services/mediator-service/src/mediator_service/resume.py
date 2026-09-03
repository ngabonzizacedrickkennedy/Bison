from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from mediator_service.dispatch import Plan, to_plan
from mediator_service.upstream import text

AWAITING_CONFIRMATION: Final[str] = "awaiting_confirmation"

STORAGE_KEYS: Final[frozenset[str]] = frozenset({"id", "plan_id", "state"})


class NotAwaitingConfirmationError(RuntimeError):
    def __init__(self, step_id: str, state: str) -> None:
        super().__init__(
            f"step {step_id} is in state {state!r}; only a step awaiting confirmation "
            "can be confirmed"
        )
        self.step_id = step_id
        self.state = state


@dataclass(frozen=True)
class Parked:
    step_id: str
    plan_id: str
    state: str


def to_parked(payload: dict[str, Any]) -> Parked:
    return Parked(
        step_id=text(payload, "id"),
        plan_id=text(payload, "plan_id"),
        state=text(payload, "state"),
    )


def assert_confirmable(parked: Parked) -> None:
    if parked.state != AWAITING_CONFIRMATION:
        raise NotAwaitingConfirmationError(parked.step_id, parked.state)


def step_payload(stored: dict[str, Any]) -> dict[str, Any]:
    carried = {key: value for key, value in stored.items() if key not in STORAGE_KEYS}

    return {**carried, "step_id": text(stored, "id")}


def plan_payload(stored: dict[str, Any]) -> dict[str, Any]:
    entries = stored.get("steps")
    listed = entries if isinstance(entries, list) else []

    return {
        **stored,
        "plan_id": text(stored, "id"),
        "steps": [step_payload(entry) for entry in listed if isinstance(entry, dict)],
    }


def rebuild(stored: dict[str, Any]) -> Plan:
    return to_plan(plan_payload(stored))
