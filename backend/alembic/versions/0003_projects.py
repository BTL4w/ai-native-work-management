"""Add tenant-scoped Projects and mutation idempotency.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_PREDICATE = (
    "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
)


def _enable_tenant_rls(table_name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY tenant_isolation ON "{table_name}" '
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE})"
        )
    )


def upgrade() -> None:
    """Create Project business storage and retry-safe mutation records."""

    idempotency_state = postgresql.ENUM(
        "IN_PROGRESS", "COMPLETED", name="idempotency_state", create_type=False
    )
    idempotency_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
    )
    op.create_index("ix_projects_timeline", "projects", ["organization_id", "created_at", "id"])
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", idempotency_state, nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "actor_membership_id", "operation", "idempotency_key"
        ),
    )
    op.create_index(
        "ix_idempotency_records_expiry",
        "idempotency_records",
        ["organization_id", "expires_at"],
    )

    for table_name in ("projects", "idempotency_records"):
        _enable_tenant_rls(table_name)
        op.execute(sa.text(f'ALTER TABLE "{table_name}" OWNER TO migration_owner'))

    op.execute("ALTER TYPE idempotency_state OWNER TO migration_owner")
    op.execute("GRANT USAGE ON TYPE idempotency_state TO app_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON projects TO app_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON idempotency_records TO app_runtime")


def downgrade() -> None:
    """Remove Project and idempotency storage."""

    op.drop_index("ix_idempotency_records_expiry", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_projects_timeline", table_name="projects")
    op.drop_table("projects")
    postgresql.ENUM(name="idempotency_state").drop(op.get_bind(), checkfirst=True)
