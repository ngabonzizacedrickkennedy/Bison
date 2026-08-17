from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from router_service import router
from router_service.broker import BrokerClient, BrokerError, BrokerUnreachableError
from router_service.config import settings
from router_service.context import RouterContext
from router_service.gating import PlanRejectedError
from router_service.persist import plan_payload
from router_service.plan import RouterParseError
from router_service.upstream import (
    PlanNotStoredError,
    ProjectClient,
    ProjectNotFoundError,
    TaskNotFoundError,
    UpstreamError,
)

SERVICE_NAME = "router-service"
WORKSPACE_DIRNAME = "workspace"


class Health(BaseModel):
    service: str
    status: Literal["ok"]
    prompt_name: str
    prompt_version: str
    project_service: str
    model_broker: str


class EffectsRead(BaseModel):
    writes_paths: list[str]
    deletes_paths: list[str]
    network: bool
    installs_packages: bool
    needs_credentials: bool
    drives_input: bool
    reversible: bool


class StepRead(BaseModel):
    step_id: str
    position: int
    description: str
    service: str
    requires_confirmation: bool
    confirmation_reason: str | None
    on_failure: str
    reversible: bool
    criterion_refs: list[str]
    effects: EffectsRead


class PlanRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    plan_id: str
    project_id: str
    task_id: str
    request_id: str
    scope_root: str
    intent: str
    rationale: str
    steps: list[StepRead]
    steps_total: int
    gated_count: int
    model_id: str
    prompt_name: str
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


@app.exception_handler(TaskNotFoundError)
async def handle_task_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "task_not_found", "detail": str(exc)})


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


@app.exception_handler(RouterParseError)
async def handle_parse(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "router_unreadable", "detail": str(exc)})


@app.exception_handler(PlanRejectedError)
async def handle_rejected(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "plan_rejected", "detail": str(exc)})


@app.exception_handler(PlanNotStoredError)
async def handle_not_stored(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=502, content={"error": "plan_not_stored", "detail": str(exc)})


@app.get("/health")
async def health() -> Health:
    resolved = settings()

    return Health(
        service=SERVICE_NAME,
        status="ok",
        prompt_name=resolved.prompt_name,
        prompt_version=resolved.prompt_version,
        project_service=resolved.project_service_url,
        model_broker=resolved.model_broker_url,
    )


@app.post("/projects/{project_id}/tasks/{task_id}/plan")
async def plan_task(project_id: str, task_id: str, request_id: str | None = None) -> PlanRead:
    resolved = settings()
    projects: ProjectClient = app.state.projects
    broker: BrokerClient = app.state.broker

    task, history = await projects.task_and_history(project_id, task_id)
    criteria = await projects.criteria(task_id)
    brief = await projects.brief(project_id)

    scope_root = str(resolved.workspace_root / project_id / WORKSPACE_DIRNAME)

    context = RouterContext(
        task=task,
        criteria=criteria,
        scope_root=scope_root,
        brief=brief,
        history=history,
    )

    correlation = request_id or str(uuid4())

    outcome = await router.run(
        broker,
        context,
        project_id=project_id,
        request_id=correlation,
        prompt_name=resolved.prompt_name,
        prompt_version=resolved.prompt_version,
        budget_chars=resolved.context_budget_chars,
        timeout_ms=int(resolved.invoke_timeout_seconds * 1000),
        repair_attempts=resolved.repair_attempts,
    )

    stored = await projects.save_plan(task_id, plan_payload(outcome, correlation, scope_root))
    identities = {
        entry["position"]: entry["id"]
        for entry in stored.get("steps", [])
        if isinstance(entry, dict)
    }

    return PlanRead(
        plan_id=str(stored["id"]),
        project_id=project_id,
        task_id=task_id,
        request_id=correlation,
        scope_root=scope_root,
        intent=outcome.plan.intent,
        rationale=outcome.plan.rationale,
        steps=[
            StepRead(
                step_id=identities[step.position],
                position=step.position,
                description=step.description,
                service=step.service,
                requires_confirmation=step.requires_confirmation,
                confirmation_reason=step.confirmation_reason,
                on_failure=step.on_failure,
                reversible=step.reversible,
                criterion_refs=step.criterion_refs,
                effects=EffectsRead(
                    writes_paths=step.effects.writes_paths,
                    deletes_paths=step.effects.deletes_paths,
                    network=step.effects.network,
                    installs_packages=step.effects.installs_packages,
                    needs_credentials=step.effects.needs_credentials,
                    drives_input=step.effects.drives_input,
                    reversible=step.effects.reversible,
                ),
            )
            for step in outcome.plan.steps
        ],
        steps_total=len(outcome.plan.steps),
        gated_count=outcome.plan.gated_count,
        model_id=outcome.model_id,
        prompt_name=outcome.prompt_name,
        prompt_version=outcome.prompt_version,
        prompt_hash=outcome.prompt_hash,
        attempts=outcome.attempts,
        repaired=outcome.repaired,
    )
