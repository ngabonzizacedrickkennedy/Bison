from __future__ import annotations

import json
from typing import Any, Final

TERMINAL_EVENTS: Final[frozenset[str]] = frozenset({"run_finished", "halted", "error"})


def encode(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")


def is_terminal(event: dict[str, Any]) -> bool:
    return event.get("event") in TERMINAL_EVENTS


def run_started(order: tuple[str, ...]) -> dict[str, Any]:
    return {
        "event": "run_started",
        "order": list(order),
        "tasks_total": len(order),
    }


def task_started(task_id: str, title: str, position: int, tasks_total: int) -> dict[str, Any]:
    return {
        "event": "task_started",
        "task_id": task_id,
        "title": title,
        "position": position,
        "tasks_total": tasks_total,
    }


def plan_ready(task_id: str, plan_id: str, steps_total: int, gated_total: int) -> dict[str, Any]:
    return {
        "event": "plan_ready",
        "task_id": task_id,
        "plan_id": plan_id,
        "steps_total": steps_total,
        "gated_total": gated_total,
    }


def step_awaiting_confirmation(
    task_id: str, step_id: str, position: int, description: str, reason: str | None
) -> dict[str, Any]:
    return {
        "event": "step_awaiting_confirmation",
        "task_id": task_id,
        "step_id": step_id,
        "position": position,
        "description": description,
        "reason": reason,
    }


def step_started(task_id: str, step_id: str, position: int, description: str) -> dict[str, Any]:
    return {
        "event": "step_started",
        "task_id": task_id,
        "step_id": step_id,
        "position": position,
        "description": description,
    }


def step_output(
    task_id: str, step_id: str, stream: str, step_sequence: int, text: str
) -> dict[str, Any]:
    return {
        "event": "step_output",
        "task_id": task_id,
        "step_id": step_id,
        "stream": stream,
        "step_sequence": step_sequence,
        "text": text,
    }


def step_finished(
    task_id: str,
    step_id: str,
    state: str,
    exit_code: int | None,
    terminated_by: str | None,
    error_message: str | None,
) -> dict[str, Any]:
    return {
        "event": "step_finished",
        "task_id": task_id,
        "step_id": step_id,
        "state": state,
        "exit_code": exit_code,
        "terminated_by": terminated_by,
        "error_message": error_message,
    }


def criterion_settled(
    task_id: str, criterion_id: str, statement: str, status: str, detail: str
) -> dict[str, Any]:
    return {
        "event": "criterion_settled",
        "task_id": task_id,
        "criterion_id": criterion_id,
        "statement": statement,
        "status": status,
        "detail": detail,
    }


def task_finished(
    task_id: str,
    state: str,
    reason: str | None,
    task_percentage: float,
    project_percentage: float,
) -> dict[str, Any]:
    return {
        "event": "task_finished",
        "task_id": task_id,
        "state": state,
        "reason": reason,
        "task_percentage": task_percentage,
        "project_percentage": project_percentage,
    }


def halted(reason: str, task_id: str | None, record_id: str | None) -> dict[str, Any]:
    return {
        "event": "halted",
        "reason": reason,
        "task_id": task_id,
        "record_id": record_id,
    }


def run_finished(
    tasks_completed: int,
    tasks_failed: int,
    tasks_total: int,
    project_percentage: float,
) -> dict[str, Any]:
    return {
        "event": "run_finished",
        "tasks_completed": tasks_completed,
        "tasks_failed": tasks_failed,
        "tasks_total": tasks_total,
        "project_percentage": project_percentage,
    }


def error(detail: str, task_id: str | None = None) -> dict[str, Any]:
    return {
        "event": "error",
        "task_id": task_id,
        "detail": detail,
    }


class Emitter:
    def __init__(self, request_id: str, project_id: str) -> None:
        self._request_id = request_id
        self._project_id = project_id
        self._sequence = 0

    @property
    def sequence(self) -> int:
        return self._sequence

    def stamp(self, event: dict[str, Any]) -> dict[str, Any]:
        stamped = {
            **event,
            "request_id": self._request_id,
            "project_id": self._project_id,
            "sequence": self._sequence,
        }
        self._sequence += 1

        return stamped

    def emit(self, event: dict[str, Any]) -> bytes:
        return encode(self.stamp(event))
