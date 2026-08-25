"""Add tenant-safe Skill taxonomy and verified evidence persistence.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
_TABLES = (
    "skills",
    "skill_versions",
    "person_skills",
    "skill_evidence",
    "work_outcome_evidence",
)
_APPEND_ONLY_TABLES = ("skill_versions", "skill_evidence", "work_outcome_evidence")


def _enable_rls(table_name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY tenant_isolation ON "{table_name}" '
            f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
        )
    )
    op.execute(sa.text(f'ALTER TABLE "{table_name}" OWNER TO migration_owner'))


def upgrade() -> None:
    """Create Skill, verification, and append-only evidence storage."""

    evidence_type = postgresql.ENUM(
        "MANAGER_NOTE",
        "CERTIFICATE",
        "COMPLETED_TASK",
        "REVIEW_OUTCOME",
        name="skill_evidence_type",
        create_type=False,
    )
    evidence_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.UniqueConstraint("organization_id", "normalized_name"),
    )
    op.create_index(
        "ix_skills_catalog", "skills", ["organization_id", "active", "normalized_name", "id"]
    )

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("changed_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "skill_id"],
            ["skills.organization_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "changed_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "skill_id", "version"),
    )
    op.create_index(
        "ix_skill_versions_history",
        "skill_versions",
        ["organization_id", "skill_id", "version", "id"],
    )

    op.create_table(
        "person_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("verified_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("level BETWEEN 1 AND 5", name="ck_person_skills_level_range"),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "skill_id"],
            ["skills.organization_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "verified_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "membership_id", "skill_id"),
    )
    op.create_index(
        "ix_person_skills_candidate_lookup",
        "person_skills",
        ["organization_id", "skill_id", "level", "membership_id"],
    )

    op.create_table(
        "skill_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("person_skill_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", evidence_type, nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_resource_type", sa.String(length=100), nullable=False),
        sa.Column("source_resource_id", sa.Uuid(), nullable=False),
        sa.Column("source_task_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(source_resource_type = 'task' AND source_task_id = source_resource_id) "
            "OR (source_resource_type <> 'task' AND source_task_id IS NULL)",
            name="ck_skill_evidence_task_source_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "person_skill_id"],
            ["person_skills.organization_id", "person_skills.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_index(
        "ix_skill_evidence_timeline",
        "skill_evidence",
        ["organization_id", "person_skill_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_skill_evidence_source",
        "skill_evidence",
        ["organization_id", "source_resource_type", "source_resource_id", "id"],
    )

    op.create_table(
        "work_outcome_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", evidence_type, nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_resource_type", sa.String(length=100), nullable=False),
        sa.Column("source_resource_id", sa.Uuid(), nullable=False),
        sa.Column("source_task_id", sa.Uuid(), nullable=True),
        sa.Column("source_resource_version", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "evidence_type IN ('COMPLETED_TASK', 'REVIEW_OUTCOME')",
            name="ck_work_outcome_evidence_type",
        ),
        sa.CheckConstraint(
            "(source_resource_type = 'task' AND source_task_id = source_resource_id) "
            "OR (source_resource_type <> 'task' AND source_task_id IS NULL)",
            name="ck_work_outcome_evidence_task_source_consistency",
        ),
        sa.CheckConstraint(
            "source_resource_version > 0",
            name="ck_work_outcome_evidence_source_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint(
            "organization_id",
            "membership_id",
            "evidence_type",
            "source_resource_id",
            "source_resource_version",
        ),
    )
    op.create_index(
        "ix_work_outcome_evidence_timeline",
        "work_outcome_evidence",
        ["organization_id", "membership_id", "observed_at", "id"],
    )
    op.create_index(
        "ix_work_outcome_evidence_source",
        "work_outcome_evidence",
        [
            "organization_id",
            "source_resource_type",
            "source_resource_id",
            "source_resource_version",
        ],
    )

    for table_name in _TABLES:
        _enable_rls(table_name)
        op.execute(sa.text(f'REVOKE ALL ON "{table_name}" FROM app_runtime'))
        if table_name in _APPEND_ONLY_TABLES:
            op.execute(sa.text(f'GRANT SELECT, INSERT ON "{table_name}" TO app_runtime'))
            op.execute(sa.text(f'REVOKE UPDATE, DELETE ON "{table_name}" FROM app_runtime'))
        else:
            op.execute(
                sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table_name}" TO app_runtime')
            )

    op.execute("ALTER TYPE skill_evidence_type OWNER TO migration_owner")
    op.execute("GRANT USAGE ON TYPE skill_evidence_type TO app_runtime")


def downgrade() -> None:
    """Remove People Skills persistence."""

    op.drop_index("ix_work_outcome_evidence_source", table_name="work_outcome_evidence")
    op.drop_index("ix_work_outcome_evidence_timeline", table_name="work_outcome_evidence")
    op.drop_table("work_outcome_evidence")
    op.drop_index("ix_skill_evidence_source", table_name="skill_evidence")
    op.drop_index("ix_skill_evidence_timeline", table_name="skill_evidence")
    op.drop_table("skill_evidence")
    op.drop_index("ix_person_skills_candidate_lookup", table_name="person_skills")
    op.drop_table("person_skills")
    op.drop_index("ix_skill_versions_history", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_index("ix_skills_catalog", table_name="skills")
    op.drop_table("skills")
    postgresql.ENUM(name="skill_evidence_type").drop(op.get_bind(), checkfirst=True)
