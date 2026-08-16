from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

ANSWER_KINDS = frozenset({"text", "choice", "file", "image", "link", "confirm"})
PROJECT_TYPES = frozenset({"code", "automation", "research", "real_world", "mixed"})

DEFAULT_CONFIDENCE_THRESHOLD = 0.75
MAX_QUESTIONS = 5


class AnalystParseError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AnalystIncompleteError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Question:
    text: str
    why_asked: str
    answer_kind: str
    choices: list[str] | None


@dataclass(frozen=True)
class AnalystDraft:
    summary: str
    interpreted_goal: str
    project_type: str
    known_constraints: list[str]
    assumptions: list[str]
    out_of_scope: list[str]
    seeded_success_criteria: list[str]
    confidence: float
    unresolved_fields: list[str]
    contradictions: list[str]
    questions: list[Question]


@dataclass(frozen=True)
class Decision:
    clarify: bool
    blocking: bool
    reasons: list[str]
    questions: list[Question]


def json_span(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise AnalystParseError("the response contained no JSON object")

    return raw[start : end + 1]


def as_object(raw: str) -> dict[str, Any]:
    try:
        parsed: Any = json.loads(json_span(raw))
    except json.JSONDecodeError as error:
        raise AnalystParseError(f"the response was not valid JSON: {error.msg}") from error

    if not isinstance(parsed, dict):
        raise AnalystParseError("the response was JSON but not an object")

    return parsed


def text_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)

    if not isinstance(value, str) or not value.strip():
        raise AnalystParseError(f"{key} must be a non-empty string")

    return value.strip()


def text_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])

    if value is None:
        return []

    if not isinstance(value, list):
        raise AnalystParseError(f"{key} must be an array of strings")

    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def confidence_field(payload: dict[str, Any]) -> float:
    value = payload.get("confidence")

    if not isinstance(value, int | float) or isinstance(value, bool):
        raise AnalystParseError("confidence must be a number between 0 and 1")

    confidence = float(value)

    if not 0.0 <= confidence <= 1.0:
        raise AnalystParseError("confidence must be between 0 and 1")

    return confidence


def project_type_field(payload: dict[str, Any]) -> str:
    value = text_field(payload, "project_type")

    if value not in PROJECT_TYPES:
        listed = ", ".join(sorted(PROJECT_TYPES))
        raise AnalystParseError(f"project_type must be one of {listed}")

    return value


def parse_question(entry: Any, position: int) -> Question:
    if not isinstance(entry, dict):
        raise AnalystParseError(f"questions[{position}] must be an object")

    text = entry.get("text")
    why_asked = entry.get("why_asked")
    answer_kind = entry.get("answer_kind")

    if not isinstance(text, str) or not text.strip():
        raise AnalystParseError(f"questions[{position}].text must be a non-empty string")

    if not isinstance(why_asked, str) or not why_asked.strip():
        raise AnalystParseError(f"questions[{position}].why_asked is required")

    if not isinstance(answer_kind, str) or answer_kind not in ANSWER_KINDS:
        listed = ", ".join(sorted(ANSWER_KINDS))
        raise AnalystParseError(f"questions[{position}].answer_kind must be one of {listed}")

    raw_choices = entry.get("choices")
    choices = (
        [item.strip() for item in raw_choices if isinstance(item, str) and item.strip()]
        if isinstance(raw_choices, list)
        else None
    )

    if answer_kind == "choice" and not choices:
        raise AnalystParseError(f"questions[{position}] is a choice and must supply choices")

    return Question(
        text=text.strip(),
        why_asked=why_asked.strip(),
        answer_kind=answer_kind,
        choices=choices if answer_kind == "choice" else None,
    )


def parse(raw: str) -> AnalystDraft:
    payload = as_object(raw)
    entries = payload.get("questions", [])

    if entries is None:
        entries = []

    if not isinstance(entries, list):
        raise AnalystParseError("questions must be an array")

    return AnalystDraft(
        summary=text_field(payload, "summary"),
        interpreted_goal=text_field(payload, "interpreted_goal"),
        project_type=project_type_field(payload),
        known_constraints=text_list(payload, "known_constraints"),
        assumptions=text_list(payload, "assumptions"),
        out_of_scope=text_list(payload, "out_of_scope"),
        seeded_success_criteria=text_list(payload, "seeded_success_criteria"),
        confidence=confidence_field(payload),
        unresolved_fields=text_list(payload, "unresolved_fields"),
        contradictions=text_list(payload, "contradictions"),
        questions=[parse_question(entry, position) for position, entry in enumerate(entries)],
    )


def decide(draft: AnalystDraft, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> Decision:
    reasons: list[str] = []

    if draft.contradictions:
        reasons.append(f"{len(draft.contradictions)} contradiction(s) in the supplied material")

    if draft.unresolved_fields:
        listed = ", ".join(draft.unresolved_fields)
        reasons.append(f"unresolved: {listed}")

    if draft.confidence < threshold:
        reasons.append(f"confidence {draft.confidence:.2f} below threshold {threshold:.2f}")

    if not reasons:
        return Decision(clarify=False, blocking=False, reasons=[], questions=[])

    if not draft.questions:
        raise AnalystIncompleteError(
            f"clarification needed ({'; '.join(reasons)}) but no questions"
        )

    return Decision(
        clarify=True,
        blocking=bool(draft.contradictions or draft.unresolved_fields),
        reasons=reasons,
        questions=draft.questions[:MAX_QUESTIONS],
    )
