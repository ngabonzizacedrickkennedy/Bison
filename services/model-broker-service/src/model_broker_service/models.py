from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RoleBindingRow(Base):
    __tablename__ = "role_binding"
    __table_args__ = (UniqueConstraint("project_id", "role", name="uq_role_binding_project_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    engine_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    locality: Mapped[str] = mapped_column(String(8), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
