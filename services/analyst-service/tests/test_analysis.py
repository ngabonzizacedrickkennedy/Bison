from __future__ import annotations

import json
from typing import Any

import pytest

from analyst_service.analysis import (
    AnalystIncompleteError,
    AnalystParseError,
    decide,
    parse,
)


def payload(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "summary": "Reconcile invoices against payments",
        "interpreted_goal": "Match every invoice to a payment",
        "project_type": "code",
        "known_constraints": ["runs offline"],
        "assumptions": ["amounts are in RWF"],
        "out_of_scope": ["tax filing"],
        "seeded_success_criteria": ["every invoice has a matched payment"],
        "confidence": 0.9,
        "unresolved_fields": [],
        "contradictions": [],
        "questions": [],
    }
    base.update(overrides)
    return json.dumps(base)


def question(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "text": "Which bank exports the statements?",
        "why_asked": "the statement format differs per bank",
        "answer_kind": "text",
    }
    base.update(overrides)
    return base


def test_parses_a_clean_brief() -> None:
    draft = parse(payload())

    assert draft.project_type == "code"
    assert draft.confidence == 0.9
    assert draft.assumptions == ["amounts are in RWF"]


def test_survives_a_fenced_response() -> None:
    fenced = f"Here is the brief:\n```json\n{payload()}\n```\n"
    draft = parse(fenced)

    assert draft.summary == "Reconcile invoices against payments"


def test_rejects_a_response_with_no_object() -> None:
    with pytest.raises(AnalystParseError, match="no JSON object"):
        parse("I need more information before I can answer.")


def test_rejects_malformed_json() -> None:
    with pytest.raises(AnalystParseError, match="not valid JSON"):
        parse('{"summary": "half a brief" "confidence": 0.9}')


def test_rejects_a_truncated_response() -> None:
    with pytest.raises(AnalystParseError, match="no JSON object"):
        parse('{"summary": "half a bra')


def test_rejects_an_unknown_project_type() -> None:
    with pytest.raises(AnalystParseError, match="project_type"):
        parse(payload(project_type="spreadsheet"))


def test_rejects_confidence_outside_the_range() -> None:
    with pytest.raises(AnalystParseError, match="between 0 and 1"):
        parse(payload(confidence=1.4))


def test_rejects_boolean_confidence() -> None:
    with pytest.raises(AnalystParseError, match="confidence"):
        parse(payload(confidence=True))


def test_rejects_a_question_without_a_reason() -> None:
    asked = question()
    del asked["why_asked"]

    with pytest.raises(AnalystParseError, match="why_asked"):
        parse(payload(questions=[asked]))


def test_rejects_a_choice_question_with_no_choices() -> None:
    with pytest.raises(AnalystParseError, match="must supply choices"):
        parse(payload(questions=[question(answer_kind="choice")]))


def test_drops_choices_from_a_text_question() -> None:
    draft = parse(payload(questions=[question(choices=["a", "b"])]))

    assert draft.questions[0].choices is None


def test_confident_and_resolved_does_not_clarify() -> None:
    verdict = decide(parse(payload()))

    assert verdict.clarify is False
    assert verdict.questions == []


def test_low_confidence_clarifies_without_blocking() -> None:
    verdict = decide(parse(payload(confidence=0.4, questions=[question()])))

    assert verdict.clarify is True
    assert verdict.blocking is False
    assert "confidence 0.40" in verdict.reasons[0]


def test_unresolved_field_blocks() -> None:
    raw = payload(unresolved_fields=["target_environment"], questions=[question()])
    verdict = decide(parse(raw))

    assert verdict.blocking is True


def test_contradiction_blocks_even_when_confident() -> None:
    raw = payload(
        confidence=0.99,
        contradictions=["the goal says offline; the material assumes a hosted API"],
        questions=[question()],
    )
    verdict = decide(parse(raw))

    assert verdict.clarify is True
    assert verdict.blocking is True


def test_questions_are_capped() -> None:
    raw = payload(confidence=0.2, questions=[question() for _ in range(9)])
    verdict = decide(parse(raw))

    assert len(verdict.questions) == 5


def test_needing_help_without_asking_is_its_own_failure() -> None:
    with pytest.raises(AnalystIncompleteError, match="no questions"):
        decide(parse(payload(confidence=0.1)))


def test_threshold_is_tunable() -> None:
    draft = parse(payload(confidence=0.6, questions=[question()]))

    assert decide(draft, threshold=0.5).clarify is False
    assert decide(draft, threshold=0.8).clarify is True
