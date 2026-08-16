from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from analyst_service import analyst
from analyst_service.analysis import AnalystIncompleteError, AnalystParseError
from analyst_service.broker import BrokerClient, BrokerError, BrokerUnreachableError
from analyst_service.config import settings
from analyst_service.context import AnalystContext
from analyst_service.upstream import ProjectClient, ProjectNotFoundError, UpstreamError

SERVICE_NAME = "analyst-service"


class Health(BaseModel):
    service: str
    status: Literal["ok"]
    prompt_version: str
    project_service: str
    model_broker: str


class QuestionRead(BaseModel):
    text: str
    why_asked: str
    answer_kind: str
    choices: list[str] | None


class BriefRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    brief_id: str
    project_id: str
    request_id: str
    conceive_revision_number: int
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
    clarify: bool
    blocking: bool
    reasons: list[str]
    questions: list[QuestionRead]
    model_id: str
    prompt_version: str
    prompt_hash: str
    attempts: int
    repaired: bool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    resolved = settings()

    app.state.projects = ProjectClient(
        resolved.project_service_url,
        resolved.upstream_timeout_seconds,
        resolved.connect_timeout_seconds,
    )
    app.state.broker = BrokerClient(
        resolved.model_broker_url,
        resolved.invoke_timeout_seconds,
        resolved.connect_timeout_seconds,
    )

    yield

    await app.state.projects.close()
    await app.state.broker.close()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.exception_handler(ProjectNotFoundError)
async def handle_project_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "project_not_found", "detail": str(exc)})


@app.exception_handler(UpstreamError)
async def handle_upstream(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"error": "upstream_unavailable", "detail": str(exc)}
    )


@app.exception_handler(BrokerUnreachableError)
async def handle_broker_unreachable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"error": "broker_unavailable", "detail": str(exc)}
    )


@app.exception_handler(BrokerError)
async def handle_broker(request: Request, exc: Exception) -> JSONResponse:
    status = exc.status if isinstance(exc, BrokerError) else 502
    return JSONResponse(status_code=status, content={"error": "broker_refused", "detail": str(exc)})


@app.exception_handler(AnalystParseError)
async def handle_parse(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "analyst_unreadable", "detail": str(exc)}
    )


@app.exception_handler(AnalystIncompleteError)
async def handle_incomplete(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "analyst_incomplete", "detail": str(exc)}
    )


@app.get("/health")
async def health() -> Health:
    resolved = settings()

    return Health(
        service=SERVICE_NAME,
        status="ok",
        prompt_version=resolved.prompt_version,
        project_service=resolved.project_service_url,
        model_broker=resolved.model_broker_url,
    )


@app.post("/projects/{project_id}/analyse")
async def analyse(project_id: str, request_id: str | None = None) -> BriefRead:
    resolved = settings()
    projects: ProjectClient = app.state.projects
    broker: BrokerClient = app.state.broker

    facts = await projects.project(project_id)
    conceive = await projects.conceive(project_id)
    materials = await projects.materials(project_id)
    answers = await projects.answers(project_id)
    prior = await projects.prior_brief(project_id)

    context = AnalystContext(
        project=facts,
        conceive=conceive,
        materials=materials,
        answers=answers,
        prior=prior,
    )

    correlation = request_id or str(uuid4())

    outcome = await analyst.run(
        broker,
        context,
        project_id=project_id,
        request_id=correlation,
        prompt_version=resolved.prompt_version,
        threshold=resolved.confidence_threshold,
        budget_chars=resolved.context_budget_chars,
        timeout_ms=int(resolved.invoke_timeout_seconds * 1000),
        repair_attempts=resolved.repair_attempts,
    )

    draft = outcome.draft
    decision = outcome.decision

    questions = [
        {
            "text": question.text,
            "why_asked": question.why_asked,
            "answer_kind": question.answer_kind,
            "choices": question.choices,
        }
        for question in decision.questions
    ]

    stored = await projects.store_brief(
        project_id,
        {
            "conceive_revision_number": conceive.revision_number,
            "summary": draft.summary,
            "interpreted_goal": draft.interpreted_goal,
            "project_type": draft.project_type,
            "known_constraints": draft.known_constraints,
            "assumptions": draft.assumptions,
            "out_of_scope": draft.out_of_scope,
            "seeded_success_criteria": draft.seeded_success_criteria,
            "confidence": draft.confidence,
            "unresolved_fields": draft.unresolved_fields,
            "contradictions": draft.contradictions,
            "model_id": outcome.model_id,
            "prompt_version": outcome.prompt_version,
            "prompt_hash": outcome.prompt_hash,
            "clarify": decision.clarify,
            "blocking": decision.blocking,
            "reasons": decision.reasons,
            "questions": questions,
        },
    )

    return BriefRead(
        brief_id=stored,
        project_id=project_id,
        request_id=correlation,
        conceive_revision_number=conceive.revision_number,
        summary=draft.summary,
        interpreted_goal=draft.interpreted_goal,
        project_type=draft.project_type,
        known_constraints=draft.known_constraints,
        assumptions=draft.assumptions,
        out_of_scope=draft.out_of_scope,
        seeded_success_criteria=draft.seeded_success_criteria,
        confidence=draft.confidence,
        unresolved_fields=draft.unresolved_fields,
        contradictions=draft.contradictions,
        clarify=decision.clarify,
        blocking=decision.blocking,
        reasons=decision.reasons,
        questions=[
            QuestionRead(
                text=question.text,
                why_asked=question.why_asked,
                answer_kind=question.answer_kind,
                choices=question.choices,
            )
            for question in decision.questions
        ],
        model_id=outcome.model_id,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        attempts=outcome.attempts,
        repaired=outcome.repaired,
    )
