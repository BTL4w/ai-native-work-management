"""PostgreSQL RLS and role integration tests for identity/organization tables."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
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
async def test_runtime_role_enforces_default_deny_and_cross_tenant_isolation() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_a = uuid4()
    organization_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    membership_a = uuid4()
    membership_b = uuid4()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) "
                    "VALUES (:id_a, :slug_a, 'Tenant A'), (:id_b, :slug_b, 'Tenant B')"
                ),
                {
                    "id_a": organization_a,
                    "slug_a": f"tenant-a-{organization_a.hex}",
                    "id_b": organization_b,
                    "slug_b": f"tenant-b-{organization_b.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id_a, :email_a, :email_a, 'User A', 'hash-a'), "
                    "(:id_b, :email_b, :email_b, 'User B', 'hash-b')"
                ),
                {
                    "id_a": user_a,
                    "email_a": f"{user_a.hex}@example.test",
                    "id_b": user_b,
                    "email_b": f"{user_b.hex}@example.test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:membership_a, :organization_a, :user_a, 'MANAGER'), "
                    "(:membership_b, :organization_b, :user_b, 'EMPLOYEE')"
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
            without_context = await connection.scalar(text("SELECT count(*) FROM memberships"))
            assert without_context == 0

            await connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(organization_a)},
            )
            visible_memberships = await connection.scalars(
                text("SELECT id FROM memberships ORDER BY id")
            )
            assert list(visible_memberships) == [membership_a]

            await connection.begin_nested()
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        "INSERT INTO auth_sessions "
                        "(id, organization_id, membership_id, token_hash, expires_at) "
                        "VALUES (:id, :organization_id, :membership_id, :token_hash, :expires_at)"
                    ),
                    {
                        "id": uuid4(),
                        "organization_id": organization_b,
                        "membership_id": membership_b,
                        "token_hash": uuid4().hex,
                        "expires_at": datetime.now(UTC) + timedelta(hours=1),
                    },
                )
            assert isinstance(error.value.orig, PsycopgError)
            assert error.value.orig.sqlstate == "42501"
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_and_owner_roles_do_not_bypass_rls() -> None:
    engine = create_database_engine(Settings(environment="test"))
    try:
        async with engine.connect() as connection:
            roles = await connection.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname IN ('app_runtime', 'migration_owner')"
                )
            )
            role_attributes = {row.rolname: row for row in roles}

            assert set(role_attributes) == {"app_runtime", "migration_owner"}
            assert role_attributes["app_runtime"].rolsuper is False
            assert role_attributes["app_runtime"].rolbypassrls is False
            assert role_attributes["migration_owner"].rolsuper is False
            assert role_attributes["migration_owner"].rolbypassrls is False

            table_owners = await connection.execute(
                text(
                    "SELECT tablename, tableowner FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "AND tablename IN "
                    "('organizations', 'users', 'memberships', 'auth_sessions', 'audit_events')"
                )
            )
            assert {row.tablename: row.tableowner for row in table_owners} == {
                "organizations": "migration_owner",
                "users": "migration_owner",
                "memberships": "migration_owner",
                "auth_sessions": "migration_owner",
                "audit_events": "migration_owner",
            }

            rls_flags = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class "
                    "WHERE relname IN ('memberships', 'auth_sessions', 'audit_events')"
                )
            )
            assert {
                row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rls_flags
            } == {
                "memberships": (True, True),
                "auth_sessions": (True, True),
                "audit_events": (True, True),
            }

            audit_privileges = await connection.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = 'app_runtime' AND table_name = 'audit_events'"
                )
            )
            assert {row.privilege_type for row in audit_privileges} == {"INSERT", "SELECT"}
    finally:
        await engine.dispose()
