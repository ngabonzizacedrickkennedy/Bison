from __future__ import annotations

from datetime import UTC, datetime

from bison_contracts import Project
from project_service.models import ProjectRow


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value


def to_project(row: ProjectRow) -> Project:
    return Project.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "goal": row.goal,
            "project_type": row.project_type,
            "state": row.state,
            "description": row.description,
            "target_environment": row.target_environment,
            "constraints": row.constraints,
            "do_not_touch": row.do_not_touch,
            "sensitivity_flags": row.sensitivity_flags,
            "success_criteria": row.success_criteria,
            "referenced_project_ids": row.referenced_project_ids,
            "created_at": aware(row.created_at),
            "updated_at": aware(row.updated_at),
            "archived_at": aware(row.archived_at),
        }
    )
