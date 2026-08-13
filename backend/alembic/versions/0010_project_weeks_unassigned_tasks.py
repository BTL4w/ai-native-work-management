"""Add Project Weeks and unassigned weekly Task planning fields.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "project_weeks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PLANNED", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("week_number > 0", name="ck_project_weeks_number_positive"),
        sa.CheckConstraint("end_date >= start_date", name="ck_project_weeks_date_order"),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'ACTIVE', 'COMPLETED')",
            name="ck_project_weeks_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "updated_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "project_id", "week_number"),
    )
    op.create_index(
        "ix_project_weeks_project_number",
        "project_weeks",
        ["organization_id", "project_id", "week_number", "id"],
    )
    op.execute(sa.text('ALTER TABLE "project_weeks" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "project_weeks" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY tenant_isolation ON "project_weeks" '
            f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
        )
    )
    op.execute(sa.text('ALTER TABLE "project_weeks" OWNER TO migration_owner'))
    op.execute(sa.text('GRANT SELECT, INSERT, UPDATE, DELETE ON "project_weeks" TO app_runtime'))

    op.add_column("tasks", sa.Column("project_week_id", sa.Uuid(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "required_skill_labels",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("tasks", sa.Column("estimated_effort_hours", sa.Integer(), nullable=True))
    op.alter_column("tasks", "assignee_membership_id", existing_type=sa.Uuid(), nullable=True)
    op.create_foreign_key(
        "fk_tasks_organization_project_week",
        "tasks",
        "project_weeks",
        ["organization_id", "project_week_id"],
        ["organization_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tasks_project_week", "tasks", ["organization_id", "project_week_id", "id"])
    op.create_check_constraint(
        "ck_tasks_estimated_effort_positive",
        "tasks",
        "estimated_effort_hours IS NULL OR estimated_effort_hours > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_estimated_effort_positive", "tasks", type_="check")
    op.drop_index("ix_tasks_project_week", table_name="tasks")
    op.drop_constraint("fk_tasks_organization_project_week", "tasks", type_="foreignkey")
    op.alter_column("tasks", "assignee_membership_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("tasks", "estimated_effort_hours")
    op.drop_column("tasks", "required_skill_labels")
    op.drop_column("tasks", "project_week_id")
    op.drop_index("ix_project_weeks_project_number", table_name="project_weeks")
    op.drop_table("project_weeks")
