from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "project"
    __table_args__ = (
        Index(
            "uq_project_single_active",
            "state",
            unique=True,
            sqlite_where=text("state = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal: Mapped[str] = mapped_column(String(500), nullable=False)
    project_type: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_environment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    constraints: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    do_not_touch: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sensitivity_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    success_criteria: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    referenced_project_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectMaterialRow(Base):
    __tablename__ = "project_material"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class UploadScanRow(Base):
    __tablename__ = "upload_scan"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    material_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("project_material.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_tree: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    languages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    dependency_manifests: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    entry_points: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    secret_findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    skipped_directories: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ConceiveRow(Base):
    __tablename__ = "conceive"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    current_revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ConceiveRevisionRow(Base):
    __tablename__ = "conceive_revision"
    __table_args__ = (
        UniqueConstraint(
            "conceive_id", "revision_number", name="uq_conceive_revision_conceive_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conceive_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conceive.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TaskNodeRow(Base):
    __tablename__ = "task_node"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("task_node.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    depends_on: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assigned_role: Mapped[str] = mapped_column(String(16), nullable=False)
    action_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AcceptanceCriterionRow(Base):
    __tablename__ = "acceptance_criterion"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("task_node.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement: Mapped[str] = mapped_column(String(500), nullable=False)
    check_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    check_spec: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="unverified")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EvidenceRefRow(Base):
    __tablename__ = "evidence_ref"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    criterion_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("acceptance_criterion.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ref: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProjectEventRow(Base):
    __tablename__ = "project_event"
    __table_args__ = (Index("ix_project_event_project_occurred", "project_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    criterion_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    material_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ProjectBriefRow(Base):
    __tablename__ = "project_brief"
    __table_args__ = (UniqueConstraint("project_id", "round", name="uq_brief_project_round"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    conceive_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    interpreted_goal: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str] = mapped_column(String(16), nullable=False)
    known_constraints: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    out_of_scope: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    seeded_success_criteria: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    unresolved_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    contradictions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ClarificationRequestRow(Base):
    __tablename__ = "clarification_request"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brief_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project_brief.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClarificationQuestionRow(Base):
    __tablename__ = "clarification_question"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clarification_request.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_value: Mapped[str] = mapped_column(Text, nullable=False)
    why_asked: Mapped[str] = mapped_column(Text, nullable=False)
    answer_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    choices: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class ClarificationAnswerRow(Base):
    __tablename__ = "clarification_answer"
    __table_args__ = (UniqueConstraint("question_id", name="uq_answer_question"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clarification_question.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    choice: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ActionPlanRow(Base):
    __tablename__ = "action_plan"
    __table_args__ = (Index("ix_action_plan_task_created", "task_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("task_node.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    scope_root: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    target_engine_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    steps_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    repaired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ActionStepRow(Base):
    __tablename__ = "action_step"
    __table_args__ = (UniqueConstraint("plan_id", "position", name="uq_step_plan_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    service: Mapped[str] = mapped_column(String(24), nullable=False)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confirmation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    on_failure: Mapped[str] = mapped_column(String(12), nullable=False, default="abort")
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    criterion_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    effects: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")


class ReconciliationRecordRow(Base):
    __tablename__ = "reconciliation_record"
    __table_args__ = (Index("ix_reconciliation_task_written", "task_id", "written_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("task_node.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    halt_reason: Mapped[str] = mapped_column(String(16), nullable=False)
    steps_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps_never_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criteria_verified_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    criteria_unverified_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    touched_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    percentage_at_halt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    plain_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    written_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class StepOutcomeRow(Base):
    __tablename__ = "step_outcome"
    __table_args__ = (UniqueConstraint("record_id", "position", name="uq_outcome_record_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reconciliation_record.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_step.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    touched_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StepTransitionRow(Base):
    __tablename__ = "step_transition"
    __table_args__ = (Index("ix_step_transition_step_occurred", "step_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    step_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_step.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("task_node.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[str] = mapped_column(String(20), nullable=False)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
