from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from bison_contracts import CatalogEntry, InvokeRequest, InvokeResponse, ModelDescriptor
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from model_broker_service import diskguard
from model_broker_service.backends import (
    BackendError,
    BackendTimeoutError,
    BackendUnavailableError,
    CircuitBrokenBackend,
    OllamaBackend,
)
from model_broker_service.broker import ModelBroker, ModelNotFoundError
from model_broker_service.catalog import (
    CatalogIndex,
    CatalogRecord,
    OllamaLibrarySource,
    OpenRouterSource,
)
from model_broker_service.config import settings
from model_broker_service.database import bind_database, configure_engine, dispose, get_session
from model_broker_service.diskguard import DiskVerdict
from model_broker_service.manifest import load_manifest
from model_broker_service.registry import ROLES, Role, RoleRegistry

SERVICE_NAME = "model-broker-service"

logger = logging.getLogger(SERVICE_NAME)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class InvokeBody(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    role: Literal["analyst", "engine", "mediator", "inspector"] = "mediator"
    mode: Literal["completion", "structured"] = "completion"
    request_id: str | None = None
    engine_id: str | None = None
    schema_name: str | None = None
    timeout_ms: int | None = None


class Health(BaseModel):
    service: str
    status: Literal["ok"]
    cache_backend: str
    backends: dict[str, str]


class CatalogStatus(BaseModel):
    entries: int
    indexed_at: datetime | None
    sources: list[str]


class BindBody(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str = Field(min_length=1)
    engine_id: str | None = None


class BindingRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    project_id: str
    role: str
    model_id: str
    engine_id: str | None
    locality: str
    prompt_version: str
    bound_at: datetime


class BudgetRead(BaseModel):
    budget_gb: float
    used_gb: float
    headroom_gb: float


def build_broker() -> ModelBroker:
    resolved = settings()

    ollama = CircuitBrokenBackend(
        OllamaBackend(resolved.ollama_base_url, resolved.connect_timeout_seconds),
        resolved.breaker_fail_max,
        resolved.breaker_reset_seconds,
    )

    return ModelBroker([ollama], resolved.local_concurrency, resolved.models_ttl_seconds)


def build_catalog() -> CatalogIndex:
    resolved = settings()

    return CatalogIndex(
        [
            OllamaLibrarySource(),
            OpenRouterSource(
                resolved.openrouter_base_url,
                resolved.catalog_fetch_timeout_seconds,
                resolved.openrouter_free_only,
            ),
        ],
        resolved.data_dir / "catalog.json",
    )


def to_entry(record: CatalogRecord, indexed_at: datetime | None) -> CatalogEntry:
    return CatalogEntry.model_validate(
        {
            "model_id": record.model_id,
            "provider": record.provider,
            "locality": record.locality,
            "size_gb": record.size_gb,
            "capability_tags": list(record.capability_tags),
            "context_window": record.context_window,
            "indexed_at": indexed_at or datetime.now(UTC),
        }
    )


async def refresh_forever(catalog: CatalogIndex, interval_seconds: float) -> None:
    while True:
        try:
            await catalog.refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("catalog refresh failed; serving the previous index")

        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    resolved = settings()
    manifest = load_manifest()

    configure_engine(bind_database(manifest.database.backend))
    app.state.local_model_gb = manifest.budgets.local_model_gb

    catalog = build_catalog()
    await catalog.load()

    app.state.cache_backend = manifest.cache.backend or "none"
    app.state.broker = build_broker()
    app.state.catalog = catalog
    app.state.refresher = asyncio.create_task(
        refresh_forever(catalog, resolved.catalog_refresh_seconds)
    )

    yield

    app.state.refresher.cancel()

    with suppress(asyncio.CancelledError):
        await app.state.refresher

    await app.state.broker.close()
    await dispose()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
async def health() -> Health:
    broker: ModelBroker = app.state.broker

    return Health(
        service=SERVICE_NAME,
        status="ok",
        cache_backend=app.state.cache_backend,
        backends=await broker.health(),
    )


@app.get("/models")
async def list_models() -> list[ModelDescriptor]:
    broker: ModelBroker = app.state.broker

    return [
        ModelDescriptor.model_validate(
            {
                "model_id": model.model_id,
                "provider": model.provider,
                "locality": model.locality,
                "size_gb": model.size_gb,
                "context_window": model.context_window,
                "installed": True,
            }
        )
        for model in await broker.list_models()
    ]


@app.post("/invoke")
async def invoke(body: InvokeBody) -> InvokeResponse:
    resolved = settings()
    broker: ModelBroker = app.state.broker

    request = InvokeRequest.model_validate(
        {
            "request_id": body.request_id or str(uuid4()),
            "model_id": body.model_id,
            "engine_id": body.engine_id,
            "role": body.role,
            "prompt": body.prompt,
            "mode": body.mode,
            "schema_name": body.schema_name,
            "timeout_ms": body.timeout_ms or int(resolved.invoke_timeout_seconds * 1000),
        }
    )

    try:
        return await broker.invoke(request)
    except ModelNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except BackendTimeoutError as error:
        raise HTTPException(status_code=504, detail=str(error)) from error
    except BackendUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/catalog/status")
async def catalog_status() -> CatalogStatus:
    catalog: CatalogIndex = app.state.catalog

    return CatalogStatus(
        entries=catalog.size,
        indexed_at=catalog.indexed_at,
        sources=["ollama", "openrouter"],
    )


@app.get("/catalog/search")
async def catalog_search(q: str = "", limit: int = 20) -> list[CatalogEntry]:
    catalog: CatalogIndex = app.state.catalog
    indexed_at = catalog.indexed_at

    return [to_entry(record, indexed_at) for record in catalog.search(q, min(limit, 200))]


@app.post("/catalog/refresh")
async def catalog_refresh() -> CatalogStatus:
    catalog: CatalogIndex = app.state.catalog
    entries = await catalog.refresh()

    return CatalogStatus(
        entries=entries,
        indexed_at=catalog.indexed_at,
        sources=["ollama", "openrouter"],
    )


async def installed_sizes() -> list[float]:
    broker: ModelBroker = app.state.broker

    return [
        model.size_gb
        for model in await broker.list_models()
        if model.locality == "local" and model.size_gb is not None
    ]


@app.get("/budget")
async def budget() -> BudgetRead:
    budget_gb: float = app.state.local_model_gb
    used_gb = round(sum(await installed_sizes()), 2)

    return BudgetRead(
        budget_gb=budget_gb,
        used_gb=used_gb,
        headroom_gb=round(budget_gb - used_gb, 2),
    )


@app.get("/projects/{project_id}/bindings")
async def list_bindings(project_id: str, session: SessionDep) -> list[BindingRead]:
    rows = await RoleRegistry(session).list_bindings(project_id)
    return [BindingRead.model_validate(row, from_attributes=True) for row in rows]


@app.put("/projects/{project_id}/bindings/{role}")
async def bind_role(
    project_id: str,
    role: Role,
    body: BindBody,
    session: SessionDep,
) -> BindingRead:
    if role not in ROLES:
        raise HTTPException(status_code=404, detail=f"unknown role {role}")

    catalog: CatalogIndex = app.state.catalog
    record = catalog.get(body.model_id)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"{body.model_id} is not in the catalog index",
        )

    row = await RoleRegistry(session).bind(
        project_id,
        role,
        body.model_id,
        record.locality,
        body.engine_id,
    )

    return BindingRead.model_validate(row, from_attributes=True)


@app.post("/models/pull/{model_id:path}")
async def pull_model(model_id: str) -> StreamingResponse:
    broker: ModelBroker = app.state.broker
    catalog: CatalogIndex = app.state.catalog
    record = catalog.get(model_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"{model_id} is not in the catalog index")

    if record.locality != "local":
        raise HTTPException(status_code=400, detail=f"{model_id} is remote and needs no pull")

    verdict = diskguard.evaluate(
        app.state.local_model_gb,
        await installed_sizes(),
        record.size_gb,
    )

    if not verdict.allowed:
        raise HTTPException(status_code=409, detail=verdict_detail(verdict))

    return StreamingResponse(stream_pull(broker, model_id), media_type="application/x-ndjson")


def verdict_detail(verdict: DiskVerdict) -> dict[str, Any]:
    return {
        "reason": verdict.reason,
        "budget_gb": verdict.budget_gb,
        "used_gb": verdict.used_gb,
        "incoming_gb": verdict.incoming_gb,
    }


async def stream_pull(broker: ModelBroker, model_id: str) -> AsyncIterator[str]:
    try:
        async for progress in broker.pull(model_id):
            payload = json.dumps(
                {
                    "status": progress.status,
                    "completed_bytes": progress.completed_bytes,
                    "total_bytes": progress.total_bytes,
                }
            )
            yield f"{payload}\n"
    except BackendError as error:
        yield f"{json.dumps({'status': 'error', 'error': str(error)})}\n"
