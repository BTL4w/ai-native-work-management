"""Add tenant-safe Capacity and Leave persistence.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT = "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
_TABLES = ("capacity_entries", "leave_entries")


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
    """Create capacity and leave storage with forced RLS and tenant integrity."""

    capacity_kind = postgresql.ENUM(
        "DEFAULT",
        "OVERRIDE",
        name="capacity_kind",
        create_type=False,
    )
    capacity_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "capacity_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("kind", capacity_kind, nullable=False),
        sa.Column("hours", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("hours BETWEEN 0 AND 168", name="ck_capacity_entries_hours"),
        sa.CheckConstraint("effective_to >= effective_from", name="ck_capacity_entries_dates"),
        sa.CheckConstraint(
            "(kind = 'DEFAULT' AND week_start IS NULL) "
            "OR (kind = 'OVERRIDE' AND week_start IS NOT NULL AND week_start = effective_from)",
            name="ck_capacity_entries_kind_week",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_index(
        "ix_capacity_entries_default_unique",
        "capacity_entries",
        ["organization_id", "membership_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'DEFAULT'"),
    )
    op.create_index(
        "ix_capacity_entries_override_unique",
        "capacity_entries",
        ["organization_id", "membership_id", "week_start"],
        unique=True,
        postgresql_where=sa.text("kind = 'OVERRIDE'"),
    )
    op.create_index(
        "ix_capacity_entries_lookup",
        "capacity_entries",
        ["organization_id", "membership_id", "kind", "effective_from", "effective_to", "id"],
    )

    op.create_table(
        "leave_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("unavailable_hours", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("unavailable_hours BETWEEN 0 AND 168", name="ck_leave_entries_hours"),
        sa.CheckConstraint("end_date >= start_date", name="ck_leave_entries_dates"),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_index(
        "ix_leave_entries_timeline",
        "leave_entries",
        ["organization_id", "membership_id", "start_date", "end_date", "id"],
    )

    for table_name in _TABLES:
        _enable_rls(table_name)
        op.execute(sa.text(f'REVOKE ALL ON "{table_name}" FROM app_runtime'))
        op.execute(
            sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table_name}" TO app_runtime')
        )

    op.execute("ALTER TYPE capacity_kind OWNER TO migration_owner")
    op.execute("GRANT USAGE ON TYPE capacity_kind TO app_runtime")


def downgrade() -> None:
    """Remove capacity and leave persistence."""

    op.drop_index("ix_leave_entries_timeline", table_name="leave_entries")
    op.drop_table("leave_entries")
    op.drop_index("ix_capacity_entries_lookup", table_name="capacity_entries")
    op.drop_index("ix_capacity_entries_override_unique", table_name="capacity_entries")
    op.drop_index("ix_capacity_entries_default_unique", table_name="capacity_entries")
    op.drop_table("capacity_entries")
    postgresql.ENUM(name="capacity_kind").drop(op.get_bind(), checkfirst=True)
