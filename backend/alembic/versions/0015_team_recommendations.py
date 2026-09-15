"""Add immutable team recommendations and approval-backed memberships.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
_TABLES = (
    "recommendations",
    "recommendation_versions",
    "candidate_scores",
    "recommendation_selections",
    "recommendation_feedback",
    "recommendation_decisions",
    "project_team_memberships",
)
_HISTORY_TABLES = _TABLES[1:-1]


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
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.CheckConstraint(
            "status IN ('PROPOSED','APPROVED','REJECTED','STALE')",
            name="ck_recommendations_status",
        ),
        sa.CheckConstraint("current_version > 0", name="ck_recommendations_version"),
    )
    op.create_index(
        "ix_recommendations_project",
        "recommendations",
        ["organization_id", "project_id", "id"],
    )
    op.create_table(
        "recommendation_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("requirement_set_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "recommendation_id"],
            ["recommendations.organization_id", "recommendations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requirement_set_id", "requirement_version"],
            [
                "team_requirement_versions.organization_id",
                "team_requirement_versions.requirement_set_id",
                "team_requirement_versions.version",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "recommendation_id", "version"),
        sa.CheckConstraint("version > 0", name="ck_recommendation_versions_version"),
    )
    op.create_index(
        "ix_recommendation_versions_history",
        "recommendation_versions",
        ["organization_id", "recommendation_id", "version"],
    )
    op.create_foreign_key(
        "fk_recommendations_current_version",
        "recommendations",
        "recommendation_versions",
        ["organization_id", "id", "current_version"],
        ["organization_id", "recommendation_id", "version"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "candidate_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_version_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id"],
            ["recommendation_versions.organization_id", "recommendation_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requirement_id"],
            ["team_requirement_items.organization_id", "team_requirement_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint(
            "organization_id", "recommendation_version_id", "requirement_id", "membership_id"
        ),
    )
    op.create_index(
        "ix_candidate_scores_version",
        "candidate_scores",
        ["organization_id", "recommendation_version_id"],
    )
    op.create_table(
        "recommendation_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_version_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_effort_hours", sa.Numeric(20, 4), nullable=False),
        sa.Column("warning_codes", postgresql.JSONB(), nullable=False),
        sa.Column("override_reason", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id", "requirement_id", "membership_id"],
            [
                "candidate_scores.organization_id",
                "candidate_scores.recommendation_version_id",
                "candidate_scores.requirement_id",
                "candidate_scores.membership_id",
            ],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint(
            "organization_id", "recommendation_version_id", "requirement_id", "membership_id"
        ),
        sa.CheckConstraint(
            "allocated_effort_hours > 0", name="ck_recommendation_selections_effort"
        ),
    )
    op.create_index(
        "ix_recommendation_selections_version",
        "recommendation_selections",
        ["organization_id", "recommendation_version_id"],
    )
    op.create_table(
        "recommendation_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_version_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("comment", sa.String(2000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id"],
            ["recommendation_versions.organization_id", "recommendation_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.CheckConstraint(
            "kind IN ('accept','override','reject')",
            name="ck_recommendation_feedback_kind",
        ),
    )
    op.create_index(
        "ix_recommendation_feedback_version",
        "recommendation_feedback",
        ["organization_id", "recommendation_version_id"],
    )
    op.create_table(
        "recommendation_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_version_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id"],
            ["recommendation_versions.organization_id", "recommendation_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "recommendation_version_id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            "project_id",
            "recommendation_version_id",
            "action",
        ),
        sa.CheckConstraint(
            "action IN ('approve','reject')", name="ck_recommendation_decisions_action"
        ),
    )
    op.create_index(
        "ix_recommendation_decisions_version",
        "recommendation_decisions",
        ["organization_id", "recommendation_version_id"],
    )
    op.create_table(
        "project_team_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_version_id", sa.Uuid(), nullable=False),
        sa.Column("decision_action", sa.String(12), server_default="approve", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        sa.ForeignKeyConstraint(
            [
                "organization_id",
                "decision_id",
                "project_id",
                "recommendation_version_id",
                "decision_action",
            ],
            [
                "recommendation_decisions.organization_id",
                "recommendation_decisions.id",
                "recommendation_decisions.project_id",
                "recommendation_decisions.recommendation_version_id",
                "recommendation_decisions.action",
            ],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.CheckConstraint("decision_action = 'approve'", name="ck_project_team_approved"),
    )
    op.create_index(
        "uq_project_team_active",
        "project_team_memberships",
        ["organization_id", "project_id", "membership_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    for table in _TABLES:
        _enable_rls(table)
    op.execute("""
        CREATE FUNCTION validate_team_recommendation_provenance() RETURNS trigger AS $$
        BEGIN
          IF TG_TABLE_NAME = 'recommendations' THEN
            IF TG_OP = 'UPDATE' AND NEW.project_id IS DISTINCT FROM OLD.project_id THEN
              RAISE EXCEPTION 'recommendation project is immutable' USING ERRCODE = '23514';
            END IF;
          ELSIF TG_TABLE_NAME = 'recommendation_versions' THEN
            IF NOT EXISTS (
              SELECT 1 FROM recommendations r
              JOIN team_requirement_versions rv
                ON rv.organization_id = NEW.organization_id
               AND rv.requirement_set_id = NEW.requirement_set_id
               AND rv.version = NEW.requirement_version
              JOIN team_requirement_sets rs
                ON rs.organization_id = rv.organization_id AND rs.id = rv.requirement_set_id
              WHERE r.organization_id = NEW.organization_id
                AND r.id = NEW.recommendation_id AND r.project_id = rs.project_id
            ) THEN
              RAISE EXCEPTION 'recommendation requirement version belongs to another project'
                USING ERRCODE = '23514';
            END IF;
          ELSIF TG_TABLE_NAME = 'candidate_scores' THEN
            IF NOT EXISTS (
              SELECT 1 FROM recommendation_versions rv
              JOIN team_requirement_versions trv
                ON trv.organization_id = rv.organization_id
               AND trv.requirement_set_id = rv.requirement_set_id
               AND trv.version = rv.requirement_version
              JOIN team_requirement_items item
                ON item.organization_id = trv.organization_id
               AND item.requirement_version_id = trv.id
              WHERE rv.organization_id = NEW.organization_id
                AND rv.id = NEW.recommendation_version_id
                AND item.id = NEW.requirement_id
            ) THEN
              RAISE EXCEPTION 'candidate requirement is outside recommendation snapshot'
                USING ERRCODE = '23514';
            END IF;
          ELSIF TG_TABLE_NAME = 'recommendation_decisions' THEN
            IF NOT EXISTS (
              SELECT 1 FROM recommendation_versions rv
              JOIN recommendations r
                ON r.organization_id = rv.organization_id AND r.id = rv.recommendation_id
              WHERE rv.organization_id = NEW.organization_id
                AND rv.id = NEW.recommendation_version_id AND r.project_id = NEW.project_id
            ) THEN
              RAISE EXCEPTION 'decision project does not match recommendation project'
                USING ERRCODE = '23514';
            END IF;
          ELSIF TG_TABLE_NAME = 'project_team_memberships' THEN
            IF TG_OP = 'UPDATE' AND (
              NEW.organization_id, NEW.project_id, NEW.membership_id, NEW.decision_id,
              NEW.recommendation_version_id, NEW.decision_action
            ) IS DISTINCT FROM (
              OLD.organization_id, OLD.project_id, OLD.membership_id, OLD.decision_id,
              OLD.recommendation_version_id, OLD.decision_action
            ) THEN
              RAISE EXCEPTION 'team membership provenance is immutable' USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (
              SELECT 1 FROM recommendation_selections selection
              WHERE selection.organization_id = NEW.organization_id
                AND selection.recommendation_version_id = NEW.recommendation_version_id
                AND selection.membership_id = NEW.membership_id
            ) THEN
              RAISE EXCEPTION 'team member was not selected in approved recommendation'
                USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """)
    provenance_events = {
        "recommendations": "UPDATE",
        "recommendation_versions": "INSERT",
        "candidate_scores": "INSERT",
        "recommendation_decisions": "INSERT",
        "project_team_memberships": "INSERT OR UPDATE",
    }
    for table, events in provenance_events.items():
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_provenance BEFORE {events} ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION validate_team_recommendation_provenance()"
            )
        )
    op.execute("""
        CREATE FUNCTION reject_recommendation_history_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'recommendation history is append-only'; END; $$ LANGUAGE plpgsql;
    """)
    for table in _HISTORY_TABLES:
        op.execute(
            sa.text(
                f'CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION reject_recommendation_history_mutation()"
            )
        )


def downgrade() -> None:
    for table in (
        "recommendations",
        "project_team_memberships",
        "recommendation_decisions",
        "candidate_scores",
        "recommendation_versions",
    ):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_provenance ON {table}"))
    op.execute("DROP FUNCTION IF EXISTS validate_team_recommendation_provenance()")
    for table in reversed(_HISTORY_TABLES):
        op.execute(sa.text(f'DROP TRIGGER IF EXISTS {table}_append_only ON "{table}"'))
    op.execute("DROP FUNCTION IF EXISTS reject_recommendation_history_mutation()")
    op.drop_table("project_team_memberships")
    op.drop_table("recommendation_decisions")
    op.drop_table("recommendation_feedback")
    op.drop_table("recommendation_selections")
    op.drop_table("candidate_scores")
    op.drop_constraint("fk_recommendations_current_version", "recommendations", type_="foreignkey")
    op.drop_table("recommendation_versions")
    op.drop_table("recommendations")
