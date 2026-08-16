from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import events
from project_service.models import (
    ClarificationAnswerRow,
    ClarificationQuestionRow,
    ClarificationRequestRow,
    ProjectBriefRow,
)
from project_service.projects import get as get_project

ANSWER_KINDS = frozenset({"text", "choice", "file", "image", "link", "confirm"})


class BriefNotFoundError(RuntimeError):
    def __init__(self, brief_id: str) -> None:
        super().__init__(f"brief {brief_id} not found")
        self.brief_id = brief_id


class QuestionNotFoundError(RuntimeError):
    def __init__(self, question_id: str) -> None:
        super().__init__(f"question {question_id} not found")
        self.question_id = question_id


class AnswerInvalidError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def next_round(session: AsyncSession, project_id: str) -> int:
    result = await session.execute(
        select(func.max(ProjectBriefRow.round)).where(ProjectBriefRow.project_id == project_id)
    )
    current = result.scalar_one_or_none()

    return 1 if current is None else int(current) + 1


async def create(
    session: AsyncSession,
    project_id: str,
    fields: dict[str, Any],
    questions: list[dict[str, Any]],
    clarify: bool,
    blocking: bool,
    reasons: list[str],
) -> ProjectBriefRow:
    await get_project(session, project_id)

    brief = ProjectBriefRow(
        project_id=project_id,
        round=await next_round(session, project_id),
        conceive_revision_number=int(fields["conceive_revision_number"]),
        summary=str(fields["summary"]),
        interpreted_goal=str(fields["interpreted_goal"]),
        project_type=str(fields["project_type"]),
        known_constraints=list(fields.get("known_constraints", [])),
        assumptions=list(fields.get("assumptions", [])),
        out_of_scope=list(fields.get("out_of_scope", [])),
        seeded_success_criteria=list(fields.get("seeded_success_criteria", [])),
        confidence=float(fields["confidence"]),
        unresolved_fields=list(fields.get("unresolved_fields", [])),
        contradictions=list(fields.get("contradictions", [])),
        model_id=str(fields["model_id"]),
        prompt_version=str(fields["prompt_version"]),
        prompt_hash=str(fields["prompt_hash"]),
    )
    session.add(brief)
    await session.flush()

    events.record(
        session,
        project_id,
        "brief.created",
        reason=f"round {brief.round}, confidence {brief.confidence:.2f}",
        actor="analyst",
    )

    if clarify and questions:
        request = ClarificationRequestRow(
            project_id=project_id,
            brief_id=brief.id,
            round=brief.round,
            blocking=blocking,
            reasons=list(reasons),
        )
        session.add(request)
        await session.flush()

        for position, question in enumerate(questions):
            session.add(
                ClarificationQuestionRow(
                    request_id=request.id,
                    position=position,
                    text_value=str(question["text"]),
                    why_asked=str(question["why_asked"]),
                    answer_kind=str(question["answer_kind"]),
                    choices=question.get("choices"),
                )
            )

        events.record(
            session,
            project_id,
            "clarification.requested",
            reason=f"round {brief.round}, {len(questions)} question(s)",
            actor="analyst",
        )

    await session.commit()
    await session.refresh(brief)

    return brief


async def get(session: AsyncSession, brief_id: str) -> ProjectBriefRow:
    row = await session.get(ProjectBriefRow, brief_id)

    if row is None:
        raise BriefNotFoundError(brief_id)

    return row


async def latest(session: AsyncSession, project_id: str) -> ProjectBriefRow | None:
    await get_project(session, project_id)

    result = await session.execute(
        select(ProjectBriefRow)
        .where(ProjectBriefRow.project_id == project_id)
        .order_by(ProjectBriefRow.round.desc())
        .limit(1)
    )

    return result.scalars().one_or_none()


async def list_briefs(session: AsyncSession, project_id: str) -> list[ProjectBriefRow]:
    await get_project(session, project_id)

    result = await session.execute(
        select(ProjectBriefRow)
        .where(ProjectBriefRow.project_id == project_id)
        .order_by(ProjectBriefRow.round.asc())
    )

    return list(result.scalars().all())


async def requests_for(session: AsyncSession, project_id: str) -> list[ClarificationRequestRow]:
    result = await session.execute(
        select(ClarificationRequestRow)
        .where(ClarificationRequestRow.project_id == project_id)
        .order_by(ClarificationRequestRow.round.asc())
    )

    return list(result.scalars().all())


async def questions_for(session: AsyncSession, request_id: str) -> list[ClarificationQuestionRow]:
    result = await session.execute(
        select(ClarificationQuestionRow)
        .where(ClarificationQuestionRow.request_id == request_id)
        .order_by(ClarificationQuestionRow.position.asc())
    )

    return list(result.scalars().all())


async def answers_for(
    session: AsyncSession, question_ids: list[str]
) -> list[ClarificationAnswerRow]:
    if not question_ids:
        return []

    result = await session.execute(
        select(ClarificationAnswerRow).where(ClarificationAnswerRow.question_id.in_(question_ids))
    )

    return list(result.scalars().all())


def validate_answer(question: ClarificationQuestionRow, fields: dict[str, Any]) -> None:
    kind = question.answer_kind

    if kind == "confirm":
        if not isinstance(fields.get("confirmed"), bool):
            raise AnswerInvalidError("a confirm question needs confirmed to be true or false")

        return

    if kind == "choice":
        choice = fields.get("choice")
        allowed = question.choices or []

        if not isinstance(choice, str) or choice not in allowed:
            listed = ", ".join(allowed)
            raise AnswerInvalidError(f"choice must be one of: {listed}")

        return

    value = fields.get("text_value")

    if not isinstance(value, str) or not value.strip():
        raise AnswerInvalidError(f"a {kind} question needs a non-empty text_value")


async def answer(
    session: AsyncSession, question_id: str, fields: dict[str, Any]
) -> ClarificationAnswerRow:
    question = await session.get(ClarificationQuestionRow, question_id)

    if question is None:
        raise QuestionNotFoundError(question_id)

    validate_answer(question, fields)

    request = await session.get(ClarificationRequestRow, question.request_id)

    if request is None:
        raise QuestionNotFoundError(question_id)

    result = await session.execute(
        select(ClarificationAnswerRow).where(ClarificationAnswerRow.question_id == question_id)
    )
    row = result.scalars().one_or_none()

    if row is None:
        row = ClarificationAnswerRow(question_id=question_id)
        session.add(row)

    row.text_value = fields.get("text_value")
    row.choice = fields.get("choice")
    row.confirmed = fields.get("confirmed")
    row.attachments = list(fields.get("attachments", []))
    row.answered_at = datetime.now(UTC)

    await session.flush()

    outstanding = await unanswered_count(session, request.id)
    request.answered_at = datetime.now(UTC) if outstanding == 0 else None

    events.record(
        session,
        request.project_id,
        "clarification.answered",
        reason=f"round {request.round}, {outstanding} remaining",
    )

    await session.commit()
    await session.refresh(row)

    return row


async def unanswered_count(session: AsyncSession, request_id: str) -> int:
    questions = await questions_for(session, request_id)
    answered = {row.question_id for row in await answers_for(session, [q.id for q in questions])}

    return sum(1 for question in questions if question.id not in answered)
