from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from bison_contracts import Project
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from project_service import conceive, materials, projects, tasks
from project_service.conceive import ConceiveReferenceError, ConceiveRevisionNotFoundError
from project_service.conceiveblocks import DuplicateBlockIdError, InvalidBlockError
from project_service.config import settings
from project_service.database import bind_database, configure_engine, dispose, get_session
from project_service.ingest import MaterialSourceInvalidError, MaterialSourceNotFoundError
from project_service.lifecycle import IllegalTransitionError
from project_service.manifest import load_manifest
from project_service.mapping import aware, to_project
from project_service.materials import (
    MaterialNotFoundError,
    MaterialSourceRequiredError,
    MaterialUrlRequiredError,
    ScanNotFoundError,
)
from project_service.models import ProjectEventRow
from project_service.progress import OVERALL_ID
from project_service.projects import ProjectCapReachedError, ProjectNotFoundError
from project_service.tasks import (
    CriterionNotFoundError,
    ParentOutsideProjectError,
    TaskNotFoundError,
    UnknownDependencyError,
)
from project_service.taskstates import IllegalTaskTransitionError, ReasonRequiredError

SERVICE_NAME = "project-service"

SessionDep = Annotated[AsyncSession, Depends(get_session)]

ProjectType = Literal["code", "automation", "research", "real_world", "mixed"]
SensitivityFlag = Literal["credentialed", "destructive", "financial", "public_facing"]


class Health(BaseModel):
    service: str
    status: Literal["ok"]
    database_backend: str
    max_projects: int


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=500)
    project_type: ProjectType
    description: str | None = None
    target_environment: str | None = None
    constraints: list[str] = Field(default_factory=list)
    do_not_touch: list[str] = Field(default_factory=list)
    sensitivity_flags: list[SensitivityFlag] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    referenced_project_ids: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, min_length=1, max_length=500)
    project_type: ProjectType | None = None
    description: str | None = None
    target_environment: str | None = None
    constraints: list[str] | None = None
    do_not_touch: list[str] | None = None
    sensitivity_flags: list[SensitivityFlag] | None = None
    success_criteria: list[str] | None = None
    referenced_project_ids: list[str] | None = None


class TransitionBody(BaseModel):
    reason: str | None = None
    actor: str = Field(default="user", max_length=16)


class EventRead(BaseModel):
    id: str
    project_id: str
    task_id: str | None
    criterion_id: str | None
    material_id: str | None
    event_type: str
    from_state: str | None
    to_state: str | None
    reason: str | None
    actor: str
    occurred_at: datetime


class ProjectList(BaseModel):
    projects: list[Project]
    open_projects: int
    max_projects: int


TaskOrigin = Literal["analyst", "engine", "mediator", "user"]
TaskKind = Literal["code", "automation", "research", "real_world", "setup", "verification"]
AssignedRole = Literal["engine", "mediator", "user"]
CheckKind = Literal["deterministic", "inspected"]
CriterionStatus = Literal["unverified", "verified", "failed", "ignored"]
TaskState = Literal[
    "pending",
    "ready",
    "in_progress",
    "blocked",
    "awaiting_confirmation",
    "awaiting_clarification",
    "verifying",
    "done",
    "failed",
    "skipped",
    "ignored",
]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    origin: TaskOrigin = "user"
    kind: TaskKind
    assigned_role: AssignedRole = "user"
    parent_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    position: int = 0


class TaskRead(BaseModel):
    id: str
    project_id: str
    parent_id: str | None
    title: str
    description: str
    origin: str
    kind: str
    state: str
    state_reason: str | None
    depends_on: list[str]
    assigned_role: str
    position: int


class TaskTransition(BaseModel):
    state: TaskState
    reason: str | None = None
    actor: str = Field(default="user", max_length=16)


class CriterionCreate(BaseModel):
    statement: str = Field(min_length=1, max_length=500)
    check_kind: CheckKind
    check_spec: dict[str, object] | None = None
    weight: int = Field(default=1, ge=1, le=100)


class CriterionRead(BaseModel):
    id: str
    task_id: str
    statement: str
    check_kind: str
    weight: int
    status: str
    status_reason: str | None
    verified_by: str | None


class CriterionStatusBody(BaseModel):
    status: CriterionStatus
    reason: str | None = None
    actor: str = Field(default="user", max_length=16)


MaterialKind = Literal["folder", "file", "image", "link"]


class MaterialCreate(BaseModel):
    kind: MaterialKind
    source_path: str | None = None
    url: str | None = None
    caption: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class MaterialRead(BaseModel):
    id: str
    project_id: str
    kind: str
    path: str | None
    url: str | None
    caption: str | None
    note: str | None
    size_bytes: int | None
    content_hash: str | None


class ScanRead(BaseModel):
    material_id: str
    total_files: int
    total_size_bytes: int
    file_tree: list[str]
    languages: list[dict[str, object]]
    dependency_manifests: list[dict[str, object]]
    entry_points: list[str]
    secret_findings: list[dict[str, object]]
    skipped_directories: list[str]
    truncated: bool


class ConceiveSave(BaseModel):
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class ConceiveRead(BaseModel):
    project_id: str
    revision_number: int
    blocks: list[dict[str, Any]]
    updated_at: datetime


class RevisionSummary(BaseModel):
    revision_number: int
    block_count: int
    created_at: datetime


class ProgressRead(BaseModel):
    task_id: str
    percentage: float
    verified_weight: float
    counted_weight: float
    criteria_total: int
    criteria_verified: int
    criteria_failed: int
    criteria_ignored: int


class ProgressSnapshotRead(BaseModel):
    project_id: str
    overall: ProgressRead
    per_task: list[ProgressRead]


def to_event(row: ProjectEventRow) -> EventRead:
    occurred_at = aware(row.occurred_at)

    if occurred_at is None:
        raise RuntimeError(f"event {row.id} has no timestamp")

    return EventRead(
        id=row.id,
        project_id=row.project_id,
        task_id=row.task_id,
        criterion_id=row.criterion_id,
        material_id=row.material_id,
        event_type=row.event_type,
        from_state=row.from_state,
        to_state=row.to_state,
        reason=row.reason,
        actor=row.actor,
        occurred_at=occurred_at,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manifest = load_manifest()
    backend = manifest.database.backend
    configure_engine(bind_database(backend))
    app.state.database_backend = backend
    yield
    await dispose()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.exception_handler(ProjectNotFoundError)
async def handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "project_not_found", "detail": str(exc)})


@app.exception_handler(ProjectCapReachedError)
async def handle_cap_reached(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"error": "project_cap_reached", "detail": str(exc)}
    )


@app.exception_handler(IllegalTransitionError)
async def handle_illegal_transition(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"error": "illegal_transition", "detail": str(exc)}
    )


@app.exception_handler(TaskNotFoundError)
async def handle_task_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "task_not_found", "detail": str(exc)})


@app.exception_handler(CriterionNotFoundError)
async def handle_criterion_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=404, content={"error": "criterion_not_found", "detail": str(exc)}
    )


@app.exception_handler(IllegalTaskTransitionError)
async def handle_illegal_task_transition(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"error": "illegal_task_transition", "detail": str(exc)}
    )


@app.exception_handler(ReasonRequiredError)
async def handle_reason_required(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "reason_required", "detail": str(exc)})


@app.exception_handler(UnknownDependencyError)
async def handle_unknown_dependency(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "unknown_dependency", "detail": str(exc)}
    )


@app.exception_handler(ParentOutsideProjectError)
async def handle_parent_outside_project(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "parent_outside_project", "detail": str(exc)}
    )


@app.exception_handler(MaterialNotFoundError)
async def handle_material_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=404, content={"error": "material_not_found", "detail": str(exc)}
    )


@app.exception_handler(ScanNotFoundError)
async def handle_scan_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "scan_not_found", "detail": str(exc)})


@app.exception_handler(MaterialSourceNotFoundError)
async def handle_source_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=404, content={"error": "material_source_not_found", "detail": str(exc)}
    )


@app.exception_handler(MaterialSourceInvalidError)
async def handle_source_invalid(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "material_source_invalid", "detail": str(exc)}
    )


@app.exception_handler(MaterialSourceRequiredError)
async def handle_source_required(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "material_source_required", "detail": str(exc)}
    )


@app.exception_handler(MaterialUrlRequiredError)
async def handle_url_required(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "material_url_required", "detail": str(exc)}
    )


@app.exception_handler(InvalidBlockError)
async def handle_invalid_block(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "invalid_block", "detail": str(exc)})


@app.exception_handler(DuplicateBlockIdError)
async def handle_duplicate_block(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "duplicate_block_id", "detail": str(exc)}
    )


@app.exception_handler(ConceiveReferenceError)
async def handle_conceive_reference(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "conceive_reference_invalid", "detail": str(exc)}
    )


@app.exception_handler(ConceiveRevisionNotFoundError)
async def handle_revision_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=404, content={"error": "conceive_revision_not_found", "detail": str(exc)}
    )


@app.get("/health")
async def health() -> Health:
    return Health(
        service=SERVICE_NAME,
        status="ok",
        database_backend=app.state.database_backend,
        max_projects=settings().max_projects,
    )


@app.post("/projects", status_code=201)
async def create_project(payload: ProjectCreate, session: SessionDep) -> Project:
    row = await projects.create(session, payload.model_dump())
    return to_project(row)


@app.get("/projects")
async def list_projects(session: SessionDep, state: str | None = None) -> ProjectList:
    rows = await projects.list_projects(session, state)
    return ProjectList(
        projects=[to_project(row) for row in rows],
        open_projects=await projects.count_open(session),
        max_projects=settings().max_projects,
    )


@app.get("/projects/{project_id}")
async def read_project(project_id: str, session: SessionDep) -> Project:
    return to_project(await projects.get(session, project_id))


@app.patch("/projects/{project_id}")
async def patch_project(project_id: str, payload: ProjectUpdate, session: SessionDep) -> Project:
    row = await projects.update(session, project_id, payload.model_dump(exclude_unset=True))
    return to_project(row)


@app.post("/projects/{project_id}/activate")
async def activate_project(
    project_id: str, payload: TransitionBody, session: SessionDep
) -> Project:
    row = await projects.transition(session, project_id, "active", payload.reason, payload.actor)
    return to_project(row)


@app.post("/projects/{project_id}/pause")
async def pause_project(project_id: str, payload: TransitionBody, session: SessionDep) -> Project:
    row = await projects.transition(session, project_id, "paused", payload.reason, payload.actor)
    return to_project(row)


@app.post("/projects/{project_id}/archive")
async def archive_project(project_id: str, payload: TransitionBody, session: SessionDep) -> Project:
    row = await projects.transition(session, project_id, "archived", payload.reason, payload.actor)
    return to_project(row)


@app.get("/projects/{project_id}/events")
async def read_events(project_id: str, session: SessionDep, limit: int = 200) -> list[EventRead]:
    await projects.get(session, project_id)
    rows = await projects.list_events(session, project_id, limit)
    return [to_event(row) for row in rows]


@app.post("/projects/{project_id}/tasks", status_code=201)
async def create_task(project_id: str, payload: TaskCreate, session: SessionDep) -> TaskRead:
    row = await tasks.create_task(session, project_id, payload.model_dump())
    return TaskRead.model_validate(row, from_attributes=True)


@app.get("/projects/{project_id}/tasks")
async def read_tasks(project_id: str, session: SessionDep) -> list[TaskRead]:
    await projects.get(session, project_id)
    rows = await tasks.list_tasks(session, project_id)
    return [TaskRead.model_validate(row, from_attributes=True) for row in rows]


@app.post("/tasks/{task_id}/state")
async def move_task(task_id: str, payload: TaskTransition, session: SessionDep) -> TaskRead:
    row = await tasks.transition_task(
        session, task_id, payload.state, payload.reason, payload.actor
    )
    return TaskRead.model_validate(row, from_attributes=True)


@app.post("/tasks/{task_id}/criteria", status_code=201)
async def create_criterion(
    task_id: str, payload: CriterionCreate, session: SessionDep
) -> CriterionRead:
    row = await tasks.create_criterion(session, task_id, payload.model_dump())
    return CriterionRead.model_validate(row, from_attributes=True)


@app.get("/tasks/{task_id}/criteria")
async def read_criteria(task_id: str, session: SessionDep) -> list[CriterionRead]:
    task = await tasks.get_task(session, task_id)
    rows = [c for c in await tasks.list_criteria(session, task.project_id) if c.task_id == task_id]
    return [CriterionRead.model_validate(row, from_attributes=True) for row in rows]


@app.post("/criteria/{criterion_id}/status")
async def move_criterion(
    criterion_id: str, payload: CriterionStatusBody, session: SessionDep
) -> CriterionRead:
    row = await tasks.set_criterion_status(
        session, criterion_id, payload.status, payload.reason, payload.actor
    )
    return CriterionRead.model_validate(row, from_attributes=True)


@app.post("/projects/{project_id}/materials", status_code=201)
async def create_material(
    project_id: str, payload: MaterialCreate, session: SessionDep
) -> MaterialRead:
    row = await materials.create_material(session, project_id, payload.model_dump())
    return MaterialRead.model_validate(row, from_attributes=True)


@app.get("/projects/{project_id}/materials")
async def read_materials(project_id: str, session: SessionDep) -> list[MaterialRead]:
    await projects.get(session, project_id)
    rows = await materials.list_materials(session, project_id)
    return [MaterialRead.model_validate(row, from_attributes=True) for row in rows]


@app.get("/materials/{material_id}")
async def read_material(material_id: str, session: SessionDep) -> MaterialRead:
    row = await materials.get_material(session, material_id)
    return MaterialRead.model_validate(row, from_attributes=True)


@app.delete("/materials/{material_id}", status_code=204)
async def remove_material(material_id: str, session: SessionDep) -> None:
    await materials.delete_material(session, material_id)


@app.get("/materials/{material_id}/scan")
async def read_scan(material_id: str, session: SessionDep) -> ScanRead:
    row = await materials.get_scan(session, material_id)
    return ScanRead.model_validate(row, from_attributes=True)


@app.post("/materials/{material_id}/rescan")
async def refresh_scan(material_id: str, session: SessionDep) -> ScanRead:
    row = await materials.rescan(session, material_id)
    return ScanRead.model_validate(row, from_attributes=True)


def to_conceive(project_id: str, revision_number: int, row: Any) -> ConceiveRead:
    blocks = row.blocks if row is not None else []
    stamp = aware(row.created_at) if row is not None else None

    return ConceiveRead(
        project_id=project_id,
        revision_number=revision_number,
        blocks=blocks,
        updated_at=stamp or datetime.now(UTC),
    )


@app.get("/projects/{project_id}/conceive")
async def read_conceive(project_id: str, session: SessionDep) -> ConceiveRead:
    row, latest = await conceive.current(session, project_id)
    return to_conceive(project_id, row.current_revision_number, latest)


@app.put("/projects/{project_id}/conceive")
async def save_conceive(
    project_id: str, payload: ConceiveSave, session: SessionDep
) -> ConceiveRead:
    row, latest = await conceive.save(session, project_id, payload.blocks)
    return to_conceive(project_id, row.current_revision_number, latest)


@app.get("/projects/{project_id}/conceive/revisions")
async def read_revisions(project_id: str, session: SessionDep) -> list[RevisionSummary]:
    await projects.get(session, project_id)
    rows = await conceive.list_revisions(session, project_id)

    return [
        RevisionSummary(
            revision_number=row.revision_number,
            block_count=len(row.blocks),
            created_at=aware(row.created_at) or datetime.now(UTC),
        )
        for row in rows
    ]


@app.get("/projects/{project_id}/conceive/revisions/{revision_number}")
async def read_revision(project_id: str, revision_number: int, session: SessionDep) -> ConceiveRead:
    row = await conceive.revision(session, project_id, revision_number)
    return to_conceive(project_id, row.revision_number, row)


@app.get("/projects/{project_id}/progress")
async def read_progress(project_id: str, session: SessionDep) -> ProgressSnapshotRead:
    computed = await tasks.snapshot(session, project_id)

    return ProgressSnapshotRead(
        project_id=project_id,
        overall=ProgressRead(**vars(computed[OVERALL_ID])),
        per_task=[
            ProgressRead(**vars(value)) for key, value in computed.items() if key != OVERALL_ID
        ],
    )
