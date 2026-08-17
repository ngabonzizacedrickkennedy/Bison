from __future__ import annotations

from bison_contracts.halt import (
    Boundary,
    HaltAcknowledgement,
    HaltSignal,
    HaltState,
    HaltStatus,
)
from fastapi import FastAPI
from pydantic import BaseModel, Field

from automation_service import SERVICE_NAME
from automation_service.config import settings

BOUNDARY: Boundary = "between_actions"

app = FastAPI(title=SERVICE_NAME)

halt_state = HaltState(SERVICE_NAME, BOUNDARY)


class ResumeBody(BaseModel):
    actor: str = Field(min_length=1)


class Health(BaseModel):
    service: str
    status: str
    boundary: str
    halted: bool
    data_dir: str


@app.get("/health")
async def health() -> Health:
    return Health(
        service=SERVICE_NAME,
        status="halted" if halt_state.halted else "ok",
        boundary=BOUNDARY,
        halted=halt_state.halted,
        data_dir=str(settings().data_dir),
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
