"""Add tenant-scoped manual planning resources.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
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


def _audit_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def _actor_constraints() -> tuple[sa.ForeignKeyConstraint, sa.ForeignKeyConstraint]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expected_outcomes", postgresql.JSONB(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
        *_actor_constraints(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "project_id"),
    )
    op.create_index("ix_goals_project", "goals", ["organization_id", "project_id", "id"])

    op.create_table(
        "milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("position > 0", name="ck_milestones_position_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
        *_actor_constraints(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_index(
        "ix_milestones_project_position",
        "milestones",
        ["organization_id", "project_id", "position", "id"],
    )

    op.add_column("tasks", sa.Column("milestone_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_organization_milestone",
        "tasks",
        "milestones",
        ["organization_id", "milestone_id"],
        ["organization_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_tasks_milestone", "tasks", ["organization_id", "milestone_id", "id"])

    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_task_id", sa.Uuid(), nullable=False),
        sa.Column("successor_task_id", sa.Uuid(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name="ck_task_dependencies_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "predecessor_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "successor_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        *_actor_constraints(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "predecessor_task_id", "successor_task_id"),
    )
    op.create_index(
        "ix_task_dependencies_predecessor",
        "task_dependencies",
        ["organization_id", "predecessor_task_id", "id"],
    )
    op.create_index(
        "ix_task_dependencies_successor",
        "task_dependencies",
        ["organization_id", "successor_task_id", "id"],
    )

    op.create_table(
        "acceptance_criteria",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("position > 0", name="ck_acceptance_criteria_position_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        *_actor_constraints(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "task_id", "text"),
    )
    op.create_index(
        "ix_acceptance_criteria_task_position",
        "acceptance_criteria",
        ["organization_id", "task_id", "position", "id"],
    )

    for table_name in ("goals", "milestones", "task_dependencies", "acceptance_criteria"):
        _enable_rls(table_name)
        op.execute(sa.text(f'ALTER TABLE "{table_name}" OWNER TO migration_owner'))
        op.execute(
            sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table_name}" TO app_runtime')
        )


def downgrade() -> None:
    op.drop_index("ix_acceptance_criteria_task_position", table_name="acceptance_criteria")
    op.drop_table("acceptance_criteria")
    op.drop_index("ix_task_dependencies_successor", table_name="task_dependencies")
    op.drop_index("ix_task_dependencies_predecessor", table_name="task_dependencies")
    op.drop_table("task_dependencies")
    op.drop_index("ix_tasks_milestone", table_name="tasks")
    op.drop_constraint("fk_tasks_organization_milestone", "tasks", type_="foreignkey")
    op.drop_column("tasks", "milestone_id")
    op.drop_index("ix_milestones_project_position", table_name="milestones")
    op.drop_table("milestones")
    op.drop_index("ix_goals_project", table_name="goals")
    op.drop_table("goals")
