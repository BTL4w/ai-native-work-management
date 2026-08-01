"""Add tenant-scoped Tasks and append-only status transitions.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_PREDICATE = (
    "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
)


def _enable_rls(table_name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY tenant_isolation ON "{table_name}" '
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE})"
        )
    )


def upgrade() -> None:
    task_status = postgresql.ENUM(
        "TO_DO", "IN_PROGRESS", "DONE", name="task_status", create_type=False
    )
    task_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assignee_membership_id", sa.Uuid(), nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "assignee_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
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
    )
    op.create_index(
        "ix_tasks_project_status", "tasks", ["organization_id", "project_id", "status", "id"]
    )
    op.create_index(
        "ix_tasks_assignee_status_due",
        "tasks",
        ["organization_id", "assignee_membership_id", "status", "due_date", "id"],
    )
    op.create_table(
        "task_status_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", task_status, nullable=False),
        sa.Column("to_status", task_status, nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("task_version_after", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_status_transitions_timeline",
        "task_status_transitions",
        ["organization_id", "task_id", "occurred_at", "id"],
    )

    for table_name in ("tasks", "task_status_transitions"):
        _enable_rls(table_name)
        op.execute(sa.text(f'ALTER TABLE "{table_name}" OWNER TO migration_owner'))
    op.execute("ALTER TYPE task_status OWNER TO migration_owner")
    op.execute("GRANT USAGE ON TYPE task_status TO app_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON tasks TO app_runtime")
    op.execute("GRANT SELECT, INSERT ON task_status_transitions TO app_runtime")


def downgrade() -> None:
    op.drop_index("ix_task_status_transitions_timeline", table_name="task_status_transitions")
    op.drop_table("task_status_transitions")
    op.drop_index("ix_tasks_assignee_status_due", table_name="tasks")
    op.drop_index("ix_tasks_project_status", table_name="tasks")
    op.drop_table("tasks")
    postgresql.ENUM(name="task_status").drop(op.get_bind(), checkfirst=True)
