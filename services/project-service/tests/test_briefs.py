from __future__ import annotations

from typing import Any

import pytest

from project_service.briefs import AnswerInvalidError, validate_answer
from project_service.models import ClarificationQuestionRow


def question(answer_kind: str, choices: list[str] | None = None) -> ClarificationQuestionRow:
    return ClarificationQuestionRow(
        request_id="r1",
        position=0,
        text_value="Which bank?",
        why_asked="the format differs per bank",
        answer_kind=answer_kind,
        choices=choices,
    )


def answer(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "text_value": None,
        "choice": None,
        "confirmed": None,
        "attachments": [],
    }
    base.update(fields)
    return base


def test_text_answer_accepts_prose() -> None:
    validate_answer(question("text"), answer(text_value="Equity Bank"))


def test_text_answer_rejects_empty() -> None:
    with pytest.raises(AnswerInvalidError, match="non-empty text_value"):
        validate_answer(question("text"), answer(text_value="   "))


def test_text_answer_rejects_missing() -> None:
    with pytest.raises(AnswerInvalidError, match="non-empty text_value"):
        validate_answer(question("text"), answer())


def test_file_and_link_answers_use_text_value() -> None:
    for kind in ("file", "image", "link"):
        validate_answer(question(kind), answer(text_value="uploads/statement.csv"))


def test_link_answer_names_its_kind_when_empty() -> None:
    with pytest.raises(AnswerInvalidError, match="a link question"):
        validate_answer(question("link"), answer())


def test_choice_answer_accepts_a_listed_option() -> None:
    validate_answer(question("choice", ["Equity", "BK"]), answer(choice="BK"))


def test_choice_answer_rejects_an_unlisted_option() -> None:
    with pytest.raises(AnswerInvalidError, match="Equity, BK"):
        validate_answer(question("choice", ["Equity", "BK"]), answer(choice="Cogebanque"))


def test_choice_answer_rejects_prose() -> None:
    with pytest.raises(AnswerInvalidError, match="choice must be one of"):
        validate_answer(question("choice", ["Equity", "BK"]), answer(text_value="Equity"))


def test_choice_answer_with_no_choices_declared_rejects_everything() -> None:
    with pytest.raises(AnswerInvalidError):
        validate_answer(question("choice"), answer(choice="anything"))


def test_confirm_answer_accepts_both_booleans() -> None:
    validate_answer(question("confirm"), answer(confirmed=True))
    validate_answer(question("confirm"), answer(confirmed=False))


def test_confirm_answer_rejects_prose() -> None:
    with pytest.raises(AnswerInvalidError, match="true or false"):
        validate_answer(question("confirm"), answer(text_value="yes"))


def test_confirm_answer_rejects_missing() -> None:
    with pytest.raises(AnswerInvalidError, match="true or false"):
        validate_answer(question("confirm"), answer())
