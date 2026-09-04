from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
from bison_contracts.halt import (
    Boundary,
    HaltAcknowledgement,
    HaltedError,
    HaltSignal,
    HaltState,
    HaltStatus,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from mediator_service import SERVICE_NAME, decomposition, resume
from mediator_service.broker import BrokerClient, BrokerError, BrokerUnreachableError
from mediator_service.config import settings
from mediator_service.context import BriefFacts, MediatorContext
from mediator_service.discipline import TreeRejectedError
from mediator_service.dispatch import RouterClient, RunnerClient
from mediator_service.execution import Clients, Resumption
from mediator_service.loop import RunLoop
from mediator_service.manifest import (
    ManifestUnavailableError,
    load_manifest,
    to_machine_facts,
)
from mediator_service.persist import (
    PartialTreeError,
    ProjectClient,
    ProjectServiceError,
    ProjectServiceUnreachableError,
    store,
)
from mediator_service.resume import NotAwaitingConfirmationError
from mediator_service.sequencing import SequencingError
from mediator_service.tree import MediatorParseError
from mediator_service.upstream import ProjectClient as UpstreamProjectClient

BOUNDARY: Boundary = "between_tasks"
WORKSPACE_DIRNAME = "workspace"
NDJSON = "application/x-ndjson"


class BriefUnavailableError(RuntimeError):
    def __init__(self, project_id: str) -> None:
        super().__init__(
            f"project {project_id} has no brief; the analyst must produce one before the tree "
            "can be built"
        )
        self.project_id = project_id


class ResumeBody(BaseModel):
    actor: str = Field(min_length=1)


class Health(BaseModel):
    service: str
    status: str
    boundary: str
    halted: bool
    data_dir: str
    project_service: str
    model_broker: str
    router_service: str
    task_runner: str


class TaskRead(BaseModel):
    ref: str
    task_id: str
    parent_ref: str | None
    title: str
    kind: str
    assigned_role: str
    depends_on: list[str]
    criterion_ids: list[str]


class DecompositionRead(BaseModel):
    project_id: str
    request_id: str
    approach_summary: str
    engine_model_id: str
    mediator_model_id: str
    engine_prompt: str
    mediator_prompt: str
    attempts: int
    repaired: bool
    execution_order: list[str]
    tasks: list[TaskRead]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    resolved = settings()
    app.state.broker = BrokerClient(
        resolved.model_broker_url,
        resolved.invoke_timeout_seconds,
        resolved.connect_timeout_seconds,
    )
    app.state.projects = ProjectClient(
        resolved.project_service_url, resolved.upstream_timeout_seconds
    )
    app.state.upstream = httpx.AsyncClient(
        base_url=resolved.project_service_url.rstrip("/"),
        timeout=httpx.Timeout(resolved.upstream_timeout_seconds),
    )

    yield

    await app.state.broker.close()
    await app.state.projects.close()
    await app.state.upstream.aclose()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

halt_state = HaltState(SERVICE_NAME, BOUNDARY)


@app.exception_handler(HaltedError)
async def on_halted(request: Request, exc: HaltedError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "halted", "detail": str(exc)})


@app.exception_handler(BriefUnavailableError)
async def on_brief_missing(request: Request, exc: BriefUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "no_brief", "detail": str(exc)})


@app.exception_handler(FileNotFoundError)
async def on_prompt_missing(request: Request, exc: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": "prompt_missing", "detail": str(exc)})


@app.exception_handler(ManifestUnavailableError)
async def on_manifest_missing(request: Request, exc: ManifestUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": "no_manifest", "detail": str(exc)})


@app.exception_handler(MediatorParseError)
async def on_unparseable(request: Request, exc: MediatorParseError) -> JSONResponse:
    return JSONResponse(
        status_code=502, content={"error": "tree_unparseable", "detail": exc.detail}
    )


@app.exception_handler(TreeRejectedError)
async def on_rejected(request: Request, exc: TreeRejectedError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "tree_rejected", "findings": list(exc.findings)},
    )


@app.exception_handler(NotAwaitingConfirmationError)
async def on_not_awaiting(request: Request, exc: NotAwaitingConfirmationError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": "not_awaiting_confirmation", "detail": str(exc)},
    )


@app.exception_handler(SequencingError)
async def on_unorderable(request: Request, exc: SequencingError) -> JSONResponse:
    return JSONResponse(
        status_code=502, content={"error": "tree_unorderable", "detail": exc.detail}
    )


@app.exception_handler(PartialTreeError)
async def on_partial(request: Request, exc: PartialTreeError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": "tree_partly_written",
            "detail": exc.detail,
            "created": list(exc.created),
            "failed_ref": exc.failed_ref,
        },
    )


@app.exception_handler(BrokerError)
async def on_broker_error(request: Request, exc: BrokerError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"error": "broker_failed", "detail": exc.detail})


@app.exception_handler(BrokerUnreachableError)
async def on_broker_unreachable(request: Request, exc: BrokerUnreachableError) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"error": "broker_unreachable", "detail": str(exc)}
    )


@app.exception_handler(ProjectServiceError)
async def on_project_error(request: Request, exc: ProjectServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=502, content={"error": "project_service_failed", "detail": exc.detail}
    )


@app.exception_handler(ProjectServiceUnreachableError)
async def on_project_unreachable(
    request: Request, exc: ProjectServiceUnreachableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"error": "project_service_unreachable", "detail": str(exc)}
    )


@app.get("/health")
async def health() -> Health:
    resolved = settings()

    return Health(
        service=SERVICE_NAME,
        status="halted" if halt_state.halted else "ok",
        boundary=BOUNDARY,
        halted=halt_state.halted,
        data_dir=str(resolved.data_dir),
        project_service=resolved.project_service_url,
        model_broker=resolved.model_broker_url,
        router_service=resolved.router_service_url,
        task_runner=resolved.task_runner_url,
    )


@app.post("/halt")
async def halt(signal: HaltSignal) -> HaltAcknowledgement:
    return halt_state.accept(signal)


@app.get("/halt/state")
async def halt_status() -> HaltStatus:
    return halt_state.status()


@app.post("/halt/resume")
async def halt_resume(body: ResumeBody) -> HaltStatus:
    return halt_state.resume(body.actor)


def to_brief_facts(payload: dict[str, Any]) -> BriefFacts:
    def strings(key: str) -> list[str]:
        value = payload.get(key)

        if not isinstance(value, list):
            return []

        return [item for item in value if isinstance(item, str) and item.strip()]

    goal = payload.get("interpreted_goal")
    project_type = payload.get("project_type")
    summary = payload.get("summary")

    return BriefFacts(
        interpreted_goal=goal if isinstance(goal, str) else "",
        project_type=project_type if isinstance(project_type, str) else "unknown",
        summary=summary if isinstance(summary, str) else "",
        known_constraints=strings("known_constraints"),
        assumptions=strings("assumptions"),
        out_of_scope=strings("out_of_scope"),
        seeded_success_criteria=strings("seeded_success_criteria"),
    )


async def read_brief(client: httpx.AsyncClient, project_id: str) -> BriefFacts:
    path = f"/projects/{project_id}/brief"

    try:
        response = await client.get(path)
    except httpx.HTTPError as error:
        raise ProjectServiceUnreachableError(str(client.base_url)) from error

    if response.status_code == httpx.codes.NOT_FOUND:
        raise BriefUnavailableError(project_id)

    if response.status_code >= httpx.codes.BAD_REQUEST:
        raise ProjectServiceError(response.status_code, f"{path} could not be read")

    parsed: Any = response.json()

    if not isinstance(parsed, dict):
        raise ProjectServiceError(response.status_code, f"{path} returned a non-object body")

    facts = to_brief_facts(parsed)

    if not facts.interpreted_goal.strip():
        raise BriefUnavailableError(project_id)

    return facts


def project_reader() -> UpstreamProjectClient:
    resolved = settings()

    return UpstreamProjectClient(resolved.project_service_url, resolved.upstream_timeout_seconds)


def clients_for_run() -> Clients:
    resolved = settings()

    return Clients(
        router=RouterClient(
            resolved.router_service_url,
            resolved.invoke_timeout_seconds,
            resolved.connect_timeout_seconds,
        ),
        runner=RunnerClient(
            resolved.task_runner_url,
            resolved.run_timeout_seconds,
            resolved.connect_timeout_seconds,
        ),
        project=UpstreamProjectClient(
            resolved.project_service_url, resolved.upstream_timeout_seconds
        ),
    )


async def drain(loop: RunLoop, clients: Clients) -> AsyncIterator[bytes]:
    try:
        async for chunk in loop.stream():
            yield chunk
    finally:
        await clients.router.close()
        await clients.runner.close()
        await clients.project.close()


@app.post("/projects/{project_id}/tree")
async def build_tree(project_id: str, request_id: str | None = None) -> DecompositionRead:
    halt_state.guard()

    resolved = settings()
    broker: BrokerClient = app.state.broker
    projects: ProjectClient = app.state.projects
    upstream: httpx.AsyncClient = app.state.upstream

    brief = await read_brief(upstream, project_id)
    machine = to_machine_facts(load_manifest())
    scope_root = str(resolved.data_dir / "projects" / project_id / WORKSPACE_DIRNAME)

    context = MediatorContext(brief=brief, machine=machine, scope_root=scope_root)
    correlation = request_id or str(uuid4())

    outcome = await decomposition.run(
        broker,
        context,
        project_id=project_id,
        request_id=correlation,
        engine_prompt_name=resolved.engine_prompt_name,
        engine_prompt_version=resolved.engine_prompt_version,
        mediator_prompt_name=resolved.mediator_prompt_name,
        mediator_prompt_version=resolved.mediator_prompt_version,
        budget_chars=resolved.context_budget_chars,
        timeout_ms=int(resolved.invoke_timeout_seconds * 1000),
        repair_attempts=resolved.repair_attempts,
    )

    stored = await store(projects, outcome.draft, outcome.ordering, project_id)

    return DecompositionRead(
        project_id=project_id,
        request_id=correlation,
        approach_summary=outcome.draft.approach_summary,
        engine_model_id=outcome.engine_model_id,
        mediator_model_id=outcome.mediator_model_id,
        engine_prompt=f"{outcome.engine_prompt.name}.{outcome.engine_prompt.version}",
        mediator_prompt=f"{outcome.mediator_prompt.name}.{outcome.mediator_prompt.version}",
        attempts=outcome.attempts,
        repaired=outcome.repaired,
        execution_order=list(outcome.ordering.order),
        tasks=[
            TaskRead(
                ref=task.ref,
                task_id=stored.task_ids[task.ref],
                parent_ref=task.parent_ref,
                title=task.title,
                kind=task.kind,
                assigned_role=task.assigned_role,
                depends_on=list(task.depends_on),
                criterion_ids=list(stored.criterion_ids[task.ref]),
            )
            for task in outcome.draft.tasks
        ],
    )


@app.post("/projects/{project_id}/run")
async def run_project(project_id: str, request_id: str | None = None) -> StreamingResponse:
    halt_state.guard()

    clients = clients_for_run()
    loop = RunLoop(clients, halt_state, project_id, request_id or str(uuid4()))

    return StreamingResponse(drain(loop, clients), media_type=NDJSON)


@app.post("/steps/{step_id}/confirm")
async def confirm_step(step_id: str, request_id: str | None = None) -> StreamingResponse:
    halt_state.guard()

    projects = project_reader()

    try:
        parked = resume.to_parked(await projects.stored_step(step_id))

        resume.assert_confirmable(parked)

        stored = await projects.stored_plan(parked.plan_id)
    finally:
        await projects.close()

    plan = resume.rebuild(stored)
    clients = clients_for_run()
    loop = RunLoop(
        clients,
        halt_state,
        plan.project_id,
        request_id or str(uuid4()),
        Resumption(plan, step_id),
    )

    return StreamingResponse(drain(loop, clients), media_type=NDJSON)
