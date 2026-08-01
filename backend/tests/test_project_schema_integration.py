"""PostgreSQL RLS and tenant-qualified constraint tests for Projects."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from psycopg import Error as PsycopgError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.core.database import create_database_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 with local PostgreSQL running",
    ),
]


@pytest.mark.asyncio
async def test_project_rls_defaults_to_deny_and_blocks_cross_tenant_writes() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_a, organization_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()
    membership_a, membership_b = uuid4(), uuid4()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:organization_a, :slug_a, 'Project Tenant A'), "
                    "(:organization_b, :slug_b, 'Project Tenant B')"
                ),
                {
                    "organization_a": organization_a,
                    "slug_a": f"project-a-{organization_a.hex}",
                    "organization_b": organization_b,
                    "slug_b": f"project-b-{organization_b.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) VALUES "
                    "(:user_a, :email_a, :email_a, 'A', 'hash'), "
                    "(:user_b, :email_b, :email_b, 'B', 'hash')"
                ),
                {
                    "user_a": user_a,
                    "email_a": f"{user_a.hex}@example.test",
                    "user_b": user_b,
                    "email_b": f"{user_b.hex}@example.test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) VALUES "
                    "(:membership_a, :organization_a, :user_a, 'MANAGER'), "
                    "(:membership_b, :organization_b, :user_b, 'MANAGER')"
                ),
                {
                    "membership_a": membership_a,
                    "organization_a": organization_a,
                    "user_a": user_a,
                    "membership_b": membership_b,
                    "organization_b": organization_b,
                    "user_b": user_b,
                },
            )
            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            assert await connection.scalar(text("SELECT count(*) FROM projects")) == 0
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(organization_a)},
            )

            await connection.begin_nested()
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        "INSERT INTO projects "
                        "(id, organization_id, name, created_by_membership_id, "
                        "updated_by_membership_id) VALUES "
                        "(:id, :organization_b, 'Cross tenant', :membership_b, :membership_b)"
                    ),
                    {
                        "id": uuid4(),
                        "organization_b": organization_b,
                        "membership_b": membership_b,
                    },
                )
            assert isinstance(error.value.orig, PsycopgError)
            assert error.value.orig.sqlstate == "42501"
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_project_tables_are_forced_rls_and_runtime_has_minimum_grants() -> None:
    engine = create_database_engine(Settings(environment="test"))
    try:
        async with engine.connect() as connection:
            flags = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('projects', 'idempotency_records')"
                )
            )
            assert {
                row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in flags
            } == {
                "projects": (True, True),
                "idempotency_records": (True, True),
            }

            grants = await connection.execute(
                text(
                    "SELECT table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE grantee = 'app_runtime' "
                    "AND table_name IN ('projects', 'idempotency_records')"
                )
            )
            by_table: dict[str, set[str]] = {}
            for row in grants:
                by_table.setdefault(row.table_name, set()).add(row.privilege_type)
            assert by_table == {
                "projects": {"INSERT", "SELECT", "UPDATE"},
                "idempotency_records": {"INSERT", "SELECT", "UPDATE"},
            }
    finally:
        await engine.dispose()
