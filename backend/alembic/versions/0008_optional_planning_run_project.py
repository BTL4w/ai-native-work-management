"""Allow a planning run to propose a project that does not exist yet.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "workflow_runs",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "workflow_runs",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
