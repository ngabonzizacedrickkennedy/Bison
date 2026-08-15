"""project event append only

Revision ID: f0516ff680a8
Revises: e6532fd9ba49
Create Date: 2026-08-15 16:16:04.518643

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f0516ff680a8'
down_revision: str | None = 'e6532fd9ba49'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TRIGGER project_event_no_update "
        "BEFORE UPDATE ON project_event "
        "BEGIN SELECT RAISE(ABORT, 'project_event is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER project_event_no_delete "
        "BEFORE DELETE ON project_event "
        "BEGIN SELECT RAISE(ABORT, 'project_event is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS project_event_no_delete")
    op.execute("DROP TRIGGER IF EXISTS project_event_no_update")
