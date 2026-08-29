"""step action

Revision ID: a7c4e91b3d02
Revises: 2526c2dce48e
Create Date: 2026-08-29 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c4e91b3d02'
down_revision: str | None = '2526c2dce48e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('action_step', schema=None) as batch_op:
        batch_op.add_column(sa.Column('action', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('action_step', schema=None) as batch_op:
        batch_op.drop_column('action')
