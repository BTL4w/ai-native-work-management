"""Add append-only audit evidence for authentication.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_PREDICATE = (
    "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
)


def upgrade() -> None:
    """Create the tenant-scoped append-only audit table and runtime grants."""

    audit_outcome = postgresql.ENUM(
        "SUCCEEDED", "REJECTED", name="audit_outcome", create_type=False
    )
    audit_outcome.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("outcome", audit_outcome, nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "before_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "after_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "reason_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_timeline",
        "audit_events",
        ["organization_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_audit_events_resource",
        "audit_events",
        ["organization_id", "resource_type", "resource_id", "occurred_at"],
    )

    op.execute(sa.text('ALTER TABLE "audit_events" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "audit_events" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY tenant_isolation ON "audit_events" '
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE})"
        )
    )

    op.execute("ALTER TYPE audit_outcome OWNER TO migration_owner")
    op.execute('ALTER TABLE "audit_events" OWNER TO migration_owner')
    op.execute("GRANT USAGE ON TYPE audit_outcome TO app_runtime")
    op.execute("GRANT SELECT, INSERT ON audit_events TO app_runtime")


def downgrade() -> None:
    """Remove auth audit storage while preserving cluster-level roles."""

    op.drop_index(
        "ix_audit_events_resource",
        table_name="audit_events",
    )
    op.drop_index("ix_audit_events_timeline", table_name="audit_events")
    op.drop_table("audit_events")
    postgresql.ENUM(name="audit_outcome").drop(op.get_bind(), checkfirst=True)
