from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from router_service.actions import Action, ActionSpecError
from router_service.actions import parse_for as parse_action

INTENTS = frozenset({"chat", "dev_task", "automation_task", "script_task", "account_action"})
SERVICES = frozenset({"task-runner", "automation", "dev-env", "engine-session"})
FAILURE_POLICIES = frozenset({"abort", "retry", "replan", "continue"})

DEFAULT_FAILURE_POLICY = "abort"
MAX_DESCRIPTION_CHARS = 500
MAX_RATIONALE_CHARS = 500
MAX_STEPS = 40


class RouterParseError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Effects:
    writes_paths: list[str]
    deletes_paths: list[str]
    network: bool
    installs_packages: bool
    needs_credentials: bool
    drives_input: bool
    reversible: bool


@dataclass(frozen=True)
class ProposedStep:
    description: str
    service: str
    action: Action | None
    effects: Effects
    on_failure: str
    criterion_refs: list[str]


@dataclass(frozen=True)
class RouterDraft:
    intent: str
    rationale: str
    steps: list[ProposedStep]


def json_span(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise RouterParseError("the response contained no JSON object")

    return raw[start : end + 1]


def as_object(raw: str) -> dict[str, Any]:
    try:
        parsed: Any = json.loads(json_span(raw))
    except json.JSONDecodeError as error:
        raise RouterParseError(f"the response was not valid JSON: {error.msg}") from error

    if not isinstance(parsed, dict):
        raise RouterParseError("the response was JSON but not an object")

    return parsed


def text_field(payload: dict[str, Any], key: str, limit: int) -> str:
    value = payload.get(key)

    if not isinstance(value, str) or not value.strip():
        raise RouterParseError(f"{key} must be a non-empty string")

    text = value.strip()

    if len(text) > limit:
        raise RouterParseError(f"{key} must be under {limit} characters")

    return text


def text_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])

    if value is None:
        return []

    if not isinstance(value, list):
        raise RouterParseError(f"{key} must be an array of strings")

    collected: list[str] = []

    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue

        stripped = item.strip()

        if stripped not in collected:
            collected.append(stripped)

    return collected


def flag(payload: dict[str, Any], key: str, missing: bool) -> bool:
    value = payload.get(key)

    return value if isinstance(value, bool) else missing


def one_of(value: Any, allowed: frozenset[str], label: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value

    listed = ", ".join(sorted(allowed))
    raise RouterParseError(f"{label} must be one of {listed}")


def parse_effects(entry: Any) -> Effects:
    payload = entry if isinstance(entry, dict) else {}

    return Effects(
        writes_paths=text_list(payload, "writes_paths"),
        deletes_paths=text_list(payload, "deletes_paths"),
        network=flag(payload, "network", True),
        installs_packages=flag(payload, "installs_packages", True),
        needs_credentials=flag(payload, "needs_credentials", True),
        drives_input=flag(payload, "drives_input", True),
        reversible=flag(payload, "reversible", False),
    )


def parse_policy(payload: dict[str, Any], position: int) -> str:
    value = payload.get("on_failure")

    if value is None:
        return DEFAULT_FAILURE_POLICY

    return one_of(value, FAILURE_POLICIES, f"steps[{position}].on_failure")


def parse_action_for(entry: dict[str, Any], service: str, position: int) -> Action | None:
    try:
        return parse_action(entry.get("action"), service, f"steps[{position}].action")
    except ActionSpecError as error:
        raise RouterParseError(error.detail) from error


def parse_step(entry: Any, position: int) -> ProposedStep:
    if not isinstance(entry, dict):
        raise RouterParseError(f"steps[{position}] must be an object")

    service = one_of(entry.get("service"), SERVICES, f"steps[{position}].service")

    return ProposedStep(
        description=text_field(entry, "description", MAX_DESCRIPTION_CHARS),
        service=service,
        action=parse_action_for(entry, service, position),
        effects=parse_effects(entry.get("effects")),
        on_failure=parse_policy(entry, position),
        criterion_refs=text_list(entry, "criterion_refs"),
    )


def parse(raw: str) -> RouterDraft:
    payload = as_object(raw)
    entries = payload.get("steps")

    if not isinstance(entries, list) or not entries:
        raise RouterParseError("steps must be a non-empty array")

    if len(entries) > MAX_STEPS:
        raise RouterParseError(f"a plan of more than {MAX_STEPS} steps is not accepted")

    return RouterDraft(
        intent=one_of(payload.get("intent"), INTENTS, "intent"),
        rationale=text_field(payload, "rationale", MAX_RATIONALE_CHARS),
        steps=[parse_step(entry, position) for position, entry in enumerate(entries)],
    )
