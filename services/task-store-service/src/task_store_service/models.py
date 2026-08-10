from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (Index("ix_tasks_user_id", "user_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (
        Index("ix_messages_request_id", "request_id"),
        Index("ix_messages_created_at", "created_at"),
    )


class ExecutionLog(Base):
    __tablename__ = "execution_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (Index("ix_execution_log_request_id", "request_id"),)
