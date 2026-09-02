from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from bison_contracts.halt import (
    Boundary,
    HaltAcknowledgement,
    HaltedError,
    HaltSignal,
    HaltState,
    HaltStatus,
)
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from task_runner_service import SERVICE_NAME
from task_runner_service.backends import NoSandboxAvailableError
from task_runner_service.config import settings
from task_runner_service.execution import Runner, build_request
from task_runner_service.manifest import ManifestUnavailableError
from task_runner_service.sandbox import (
    InvalidSandboxRequestError,
    Mount,
    ProgramKindUnsupportedError,
)
from task_runner_service.scope import ScopeRootError, StepRefusedError, assert_admissible
from task_runner_service.stream import encode, write_event
from task_runner_service.venvs import EnvironmentUnavailableError
from task_runner_service.writes import WriteRefusedError, perform

BOUNDARY: Boundary = "immediate"

NDJSON = "application/x-ndjson"

app = FastAPI(title=SERVICE_NAME)

halt_state = HaltState(SERVICE_NAME, BOUNDARY)

runner = Runner()


class ResumeBody(BaseModel):
    actor: str = Field(min_length=1)


class TerminateBody(BaseModel):
    actor: str = Field(min_length=1)


class RunBody(BaseModel):
    scope_root: str = Field(min_length=1)
    task_id: str | None = None
    step: dict[str, Any]
    confirmed: bool = False
    program: str = Field(min_length=1)
    arguments: list[str] = Field(default_factory=list)
    working_directory: str | None = None
    read_only_mounts: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    network: bool = False
    limits: dict[str, int] | None = None


class WriteBody(BaseModel):
    scope_root: str = Field(min_length=1)
    task_id: str | None = None
    step: dict[str, Any]
    confirmed: bool = False
    path: str = Field(min_length=1)
    content: str


class Health(BaseModel):
    service: str
    status: str
    boundary: str
    halted: bool
    data_dir: str
    running: list[str]


class BackendReport(BaseModel):
    backend: str
    accepts: list[str]
    filesystem_write_scope: bool
    filesystem_read_scope: bool
    network_isolation: bool
    memory_limit: bool
    process_tree_kill: bool


@app.get("/health")
async def health() -> Health:
    return Health(
        service=SERVICE_NAME,
        status="halted" if halt_state.halted else "ok",
        boundary=BOUNDARY,
        halted=halt_state.halted,
        data_dir=str(settings().data_dir),
        running=sorted(runner.active),
    )


@app.get("/sandboxes")
async def sandboxes() -> list[BackendReport]:
    return [
        BackendReport(
            backend=sandbox.backend.value,
            accepts=sorted(sandbox.accepts),
            filesystem_write_scope=sandbox.enforcement.filesystem_write_scope,
            filesystem_read_scope=sandbox.enforcement.filesystem_read_scope,
            network_isolation=sandbox.enforcement.network_isolation,
            memory_limit=sandbox.enforcement.memory_limit,
            process_tree_kill=sandbox.enforcement.process_tree_kill,
        )
        for sandbox in runner.available
    ]


@app.post("/halt")
async def halt(signal: HaltSignal) -> HaltAcknowledgement:
    acknowledgement = halt_state.accept(signal)

    await runner.terminate_all("halt")

    return acknowledgement


@app.get("/halt/state")
async def halt_status() -> HaltStatus:
    return halt_state.status()


@app.post("/halt/resume")
async def halt_resume(body: ResumeBody) -> HaltStatus:
    return halt_state.resume(body.actor)


@app.post("/steps/{step_id}/terminate")
async def terminate_step(step_id: str, body: TerminateBody) -> dict[str, bool]:
    return {"terminated": await runner.terminate(step_id, "step_abort")}


@app.post("/steps/{step_id}/run")
async def run_step(step_id: str, body: RunBody) -> StreamingResponse:
    try:
        halt_state.guard()
    except HaltedError as halted:
        raise HTTPException(status_code=409, detail=str(halted)) from halted

    try:
        assert_admissible(body.step, body.scope_root, body.confirmed)
    except StepRefusedError as refused:
        raise HTTPException(status_code=403, detail=str(refused)) from refused
    except ScopeRootError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid

    try:
        request = build_request(step_id, body.model_dump(exclude_none=True), body.scope_root)
        binding = runner.plan(request)
        key = body.task_id if body.task_id else step_id
        request = await runner.provision(request, key, binding)
    except ManifestUnavailableError as unavailable:
        raise HTTPException(status_code=503, detail=str(unavailable)) from unavailable
    except EnvironmentUnavailableError as unavailable:
        raise HTTPException(status_code=503, detail=str(unavailable)) from unavailable
    except (KeyError, ValueError, InvalidSandboxRequestError, ScopeRootError) as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid
    except (NoSandboxAvailableError, ProgramKindUnsupportedError) as conflict:
        raise HTTPException(status_code=409, detail=str(conflict)) from conflict

    return StreamingResponse(
        runner.stream(request, binding),
        media_type=NDJSON,
        headers={
            "x-bison-sandbox-backend": binding.backend.value,
            "x-bison-sandbox-degraded": "true" if binding.degraded else "false",
        },
    )


@app.post("/steps/{step_id}/write")
async def write_step(step_id: str, body: WriteBody) -> StreamingResponse:
    try:
        halt_state.guard()
    except HaltedError as halted:
        raise HTTPException(status_code=409, detail=str(halted)) from halted

    try:
        assert_admissible(body.step, body.scope_root, body.confirmed)
    except StepRefusedError as refused:
        raise HTTPException(status_code=403, detail=str(refused)) from refused
    except ScopeRootError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid

    mounts = [Mount(path=body.scope_root, writable=True)]

    try:
        result = perform(step_id, body.path, body.content, mounts)
    except WriteRefusedError as refused:
        raise HTTPException(status_code=403, detail=refused.detail) from refused
    except ScopeRootError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid

    async def single() -> AsyncIterator[bytes]:
        yield encode(write_event(result))

    return StreamingResponse(single(), media_type=NDJSON)
