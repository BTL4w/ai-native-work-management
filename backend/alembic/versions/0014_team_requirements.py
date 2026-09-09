"""Add immutable, tenant-safe Project Team requirement snapshots.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
_TABLES = (
    "team_requirement_sets",
    "team_requirement_versions",
    "team_requirement_items",
    "team_requirement_task_sources",
)


def _enable_rls(table: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY tenant_isolation ON "{table}" USING ({_TENANT}) WITH CHECK ({_TENANT})'
        )
    )
    op.execute(sa.text(f'ALTER TABLE "{table}" OWNER TO migration_owner'))
    op.execute(sa.text(f'REVOKE ALL ON "{table}" FROM app_runtime'))
    op.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO app_runtime'))


def upgrade() -> None:
    op.create_table(
        "team_requirement_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(12), server_default="DRAFT", nullable=False),
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
        sa.UniqueConstraint("organization_id", "project_id"),
        sa.CheckConstraint("version > 0", name="ck_team_requirement_sets_version_positive"),
        sa.CheckConstraint(
            "current_version IS NULL OR current_version > 0",
            name="ck_team_requirement_sets_current_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'STALE')", name="ck_team_requirement_sets_status"
        ),
    )
    op.create_index(
        "ix_team_requirement_sets_project",
        "team_requirement_sets",
        ["organization_id", "project_id", "id"],
    )
    op.create_table(
        "team_requirement_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_set_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column(
            "incomplete_items",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "task_provenance",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requirement_set_id"],
            ["team_requirement_sets.organization_id", "team_requirement_sets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "requirement_set_id", "version"),
        sa.CheckConstraint("version > 0", name="ck_team_requirement_versions_version_positive"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'STALE')", name="ck_team_requirement_versions_status"
        ),
    )
    op.create_index(
        "ix_team_requirement_versions_history",
        "team_requirement_versions",
        ["organization_id", "requirement_set_id", "version", "id"],
    )
    op.create_foreign_key(
        "fk_team_requirement_sets_current_version",
        "team_requirement_sets",
        "team_requirement_versions",
        ["organization_id", "id", "current_version"],
        ["organization_id", "requirement_set_id", "version"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "team_requirement_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_version_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("minimum_level", sa.Integer(), nullable=False),
        sa.Column("project_week_id", sa.Uuid(), nullable=False),
        sa.Column("effort_hours", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requirement_version_id"],
            ["team_requirement_versions.organization_id", "team_requirement_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "skill_id"],
            ["skills.organization_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_week_id"],
            ["project_weeks.organization_id", "project_weeks.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint(
            "organization_id", "requirement_version_id", "skill_id", "project_week_id"
        ),
        sa.CheckConstraint("minimum_level BETWEEN 1 AND 5", name="ck_team_requirement_items_level"),
        sa.CheckConstraint("effort_hours > 0", name="ck_team_requirement_items_effort_positive"),
    )
    op.create_index(
        "ix_team_requirement_items_version",
        "team_requirement_items",
        ["organization_id", "requirement_version_id", "project_week_id", "skill_id", "id"],
    )
    op.create_table(
        "team_requirement_task_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_item_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requirement_item_id"],
            ["team_requirement_items.organization_id", "team_requirement_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "requirement_item_id", "task_id"),
        sa.CheckConstraint(
            "task_version > 0", name="ck_team_requirement_task_sources_version_positive"
        ),
    )
    op.create_index(
        "ix_team_requirement_task_sources_item",
        "team_requirement_task_sources",
        ["organization_id", "requirement_item_id", "task_id", "id"],
    )
    for table in _TABLES:
        _enable_rls(table)
    op.execute("""
        CREATE FUNCTION reject_team_requirement_history_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'team requirement history is append-only'; END; $$ LANGUAGE plpgsql;
    """)
    for table in _TABLES[1:]:
        op.execute(
            sa.text(
                f'CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION reject_team_requirement_history_mutation()"
            )
        )


def downgrade() -> None:
    for table in reversed(_TABLES[1:]):
        op.execute(sa.text(f'DROP TRIGGER IF EXISTS {table}_append_only ON "{table}"'))
    op.execute("DROP FUNCTION IF EXISTS reject_team_requirement_history_mutation()")
    op.drop_table("team_requirement_task_sources")
    op.drop_table("team_requirement_items")
    op.drop_constraint(
        "fk_team_requirement_sets_current_version",
        "team_requirement_sets",
        type_="foreignkey",
    )
    op.drop_table("team_requirement_versions")
    op.drop_table("team_requirement_sets")
