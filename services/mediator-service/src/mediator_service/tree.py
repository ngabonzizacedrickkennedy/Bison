from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from mediator_service.checks import CheckSpec, CheckSpecError
from mediator_service.checks import parse as parse_check

TASK_KINDS: Final[frozenset[str]] = frozenset(
    {"code", "automation", "research", "real_world", "setup", "verification"}
)

ASSIGNED_ROLES: Final[frozenset[str]] = frozenset({"engine", "mediator", "user"})

CHECK_KINDS: Final[frozenset[str]] = frozenset({"deterministic", "inspected"})

MAX_TASKS: Final[int] = 60
MAX_CRITERIA_PER_TASK: Final[int] = 20
MAX_REF_CHARS: Final[int] = 64
MAX_TITLE_CHARS: Final[int] = 200
MAX_DESCRIPTION_CHARS: Final[int] = 2000
MAX_STATEMENT_CHARS: Final[int] = 500
MAX_SUMMARY_CHARS: Final[int] = 2000

MIN_WEIGHT: Final[int] = 1
MAX_WEIGHT: Final[int] = 100
DEFAULT_WEIGHT: Final[int] = 1


class MediatorParseError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class DraftCriterion:
    statement: str
    check_kind: str
    check_spec: CheckSpec | None
    weight: int


@dataclass(frozen=True)
class DraftTask:
    ref: str
    parent_ref: str | None
    title: str
    description: str
    kind: str
    assigned_role: str
    depends_on: tuple[str, ...]
    criteria: tuple[DraftCriterion, ...]
    position: int


@dataclass(frozen=True)
class TreeDraft:
    approach_summary: str
    tasks: tuple[DraftTask, ...]


def leaf_refs(draft: TreeDraft) -> frozenset[str]:
    parents = {task.parent_ref for task in draft.tasks if task.parent_ref is not None}

    return frozenset(task.ref for task in draft.tasks if task.ref not in parents)


def json_span(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise MediatorParseError("the response contained no JSON object")

    return raw[start : end + 1]


def as_object(raw: str) -> dict[str, Any]:
    try:
        parsed: Any = json.loads(json_span(raw))
    except json.JSONDecodeError as error:
        raise MediatorParseError(f"the response was not valid JSON: {error.msg}") from error

    if not isinstance(parsed, dict):
        raise MediatorParseError("the response was JSON but not an object")

    return parsed


def text(source: dict[str, Any], key: str, label: str, limit: int) -> str:
    value = source.get(key)

    if not isinstance(value, str) or not value.strip():
        raise MediatorParseError(f"{label}.{key} must be a non-empty string")

    stripped = value.strip()

    if len(stripped) > limit:
        raise MediatorParseError(f"{label}.{key} must be under {limit} characters")

    return stripped


def optional_text(source: dict[str, Any], key: str, label: str, limit: int) -> str:
    value = source.get(key)

    if value is None:
        return ""

    if not isinstance(value, str):
        raise MediatorParseError(f"{label}.{key} must be a string")

    stripped = value.strip()

    if len(stripped) > limit:
        raise MediatorParseError(f"{label}.{key} must be under {limit} characters")

    return stripped


def optional_ref(source: dict[str, Any], key: str, label: str) -> str | None:
    value = source.get(key)

    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise MediatorParseError(f"{label}.{key} must be a task ref or null")

    stripped = value.strip()

    if len(stripped) > MAX_REF_CHARS:
        raise MediatorParseError(f"{label}.{key} must be under {MAX_REF_CHARS} characters")

    return stripped


def ref_list(source: dict[str, Any], key: str, label: str) -> tuple[str, ...]:
    value = source.get(key, [])

    if value is None:
        return ()

    if not isinstance(value, list):
        raise MediatorParseError(f"{label}.{key} must be an array of task refs")

    collected: list[str] = []

    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MediatorParseError(f"{label}.{key} must contain only task refs")

        stripped = item.strip()

        if stripped not in collected:
            collected.append(stripped)

    return tuple(collected)


def one_of(source: dict[str, Any], key: str, label: str, allowed: frozenset[str]) -> str:
    value = source.get(key)

    if isinstance(value, str) and value.strip() in allowed:
        return value.strip()

    listed = ", ".join(sorted(allowed))
    raise MediatorParseError(f"{label}.{key} must be one of {listed}")


def weight_of(source: dict[str, Any], label: str) -> int:
    value = source.get("weight")

    if value is None:
        return DEFAULT_WEIGHT

    if isinstance(value, bool) or not isinstance(value, int):
        raise MediatorParseError(f"{label}.weight must be a whole number")

    if value < MIN_WEIGHT or value > MAX_WEIGHT:
        raise MediatorParseError(f"{label}.weight must be between {MIN_WEIGHT} and {MAX_WEIGHT}")

    return value


def parse_criterion(entry: Any, label: str) -> DraftCriterion:
    if not isinstance(entry, dict):
        raise MediatorParseError(f"{label} must be an object")

    check_kind = one_of(entry, "check_kind", label, CHECK_KINDS)
    supplied = entry.get("check_spec")

    if check_kind == "deterministic" and supplied is None:
        raise MediatorParseError(
            f"{label} is deterministic and must carry a check_spec saying how it is checked"
        )

    if check_kind == "inspected" and supplied is not None:
        raise MediatorParseError(
            f"{label} is inspected and must have check_spec null; "
            "a criterion a check_spec can settle is deterministic"
        )

    if supplied is None:
        check_spec = None
    else:
        try:
            check_spec = parse_check(supplied, f"{label}.check_spec")
        except CheckSpecError as error:
            raise MediatorParseError(error.detail) from error

    return DraftCriterion(
        statement=text(entry, "statement", label, MAX_STATEMENT_CHARS),
        check_kind=check_kind,
        check_spec=check_spec,
        weight=weight_of(entry, label),
    )


def parse_criteria(entry: Any, label: str) -> tuple[DraftCriterion, ...]:
    if entry is None:
        return ()

    if not isinstance(entry, list):
        raise MediatorParseError(f"{label}.criteria must be an array")

    if len(entry) > MAX_CRITERIA_PER_TASK:
        raise MediatorParseError(
            f"{label}.criteria must hold no more than {MAX_CRITERIA_PER_TASK} entries"
        )

    return tuple(
        parse_criterion(item, f"{label}.criteria[{index}]") for index, item in enumerate(entry)
    )


def parse_task(entry: Any, index: int) -> DraftTask:
    label = f"tasks[{index}]"

    if not isinstance(entry, dict):
        raise MediatorParseError(f"{label} must be an object")

    return DraftTask(
        ref=text(entry, "ref", label, MAX_REF_CHARS),
        parent_ref=optional_ref(entry, "parent_ref", label),
        title=text(entry, "title", label, MAX_TITLE_CHARS),
        description=optional_text(entry, "description", label, MAX_DESCRIPTION_CHARS),
        kind=one_of(entry, "kind", label, TASK_KINDS),
        assigned_role=one_of(entry, "assigned_role", label, ASSIGNED_ROLES),
        depends_on=ref_list(entry, "depends_on", label),
        criteria=parse_criteria(entry.get("criteria"), label),
        position=0,
    )


def assert_refs_resolve(tasks: list[DraftTask]) -> None:
    known: set[str] = set()

    for task in tasks:
        if task.ref in known:
            raise MediatorParseError(f"task ref {task.ref} is used more than once")

        known.add(task.ref)

    for index, task in enumerate(tasks):
        if task.parent_ref is not None and task.parent_ref not in known:
            raise MediatorParseError(
                f"tasks[{index}].parent_ref names {task.parent_ref}, which is not a task in "
                "this tree"
            )

        for dependency in task.depends_on:
            if dependency not in known:
                raise MediatorParseError(
                    f"tasks[{index}].depends_on names {dependency}, which is not a task in "
                    "this tree"
                )


def positioned(tasks: list[DraftTask]) -> tuple[DraftTask, ...]:
    counters: dict[str | None, int] = {}
    placed: list[DraftTask] = []

    for task in tasks:
        position = counters.get(task.parent_ref, 0)
        counters[task.parent_ref] = position + 1
        placed.append(
            DraftTask(
                ref=task.ref,
                parent_ref=task.parent_ref,
                title=task.title,
                description=task.description,
                kind=task.kind,
                assigned_role=task.assigned_role,
                depends_on=task.depends_on,
                criteria=task.criteria,
                position=position,
            )
        )

    return tuple(placed)


def parse(raw: str) -> TreeDraft:
    payload = as_object(raw)
    entries = payload.get("tasks")

    if not isinstance(entries, list) or not entries:
        raise MediatorParseError("tasks must be a non-empty array")

    if len(entries) > MAX_TASKS:
        raise MediatorParseError(f"a tree of more than {MAX_TASKS} tasks is not accepted")

    tasks = [parse_task(entry, index) for index, entry in enumerate(entries)]
    assert_refs_resolve(tasks)

    return TreeDraft(
        approach_summary=text(payload, "approach_summary", "tree", MAX_SUMMARY_CHARS),
        tasks=positioned(tasks),
    )
