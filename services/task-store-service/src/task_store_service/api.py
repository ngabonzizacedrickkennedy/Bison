from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from task_store_service.database import dispose, get_session
from task_store_service.models import ExecutionLog, Message

SERVICE_NAME = "task-store-service"


class MessageCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)
    user_id: str = Field(min_length=1, max_length=64)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class MessageRead(BaseModel):
    id: str
    request_id: str
    user_id: str
    role: str
    content: str
    created_at: datetime


class Health(BaseModel):
    service: str
    status: Literal["ok"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@app.get("/health")
async def health() -> Health:
    return Health(service=SERVICE_NAME, status="ok")


@app.post("/messages", status_code=201)
async def create_message(payload: MessageCreate, session: SessionDep) -> MessageRead:
    message = Message(
        request_id=payload.request_id,
        user_id=payload.user_id,
        role=payload.role,
        content=payload.content,
    )
    session.add(message)

    session.add(
        ExecutionLog(
            request_id=payload.request_id,
            event="message.persisted",
            detail=payload.role,
        )
    )

    await session.commit()
    await session.refresh(message)

    return MessageRead.model_validate(message, from_attributes=True)


@app.get("/messages")
async def list_messages(session: SessionDep, limit: int = 100) -> list[MessageRead]:
    result = await session.execute(select(Message).order_by(Message.created_at.asc()).limit(limit))
    return [MessageRead.model_validate(row, from_attributes=True) for row in result.scalars().all()]
