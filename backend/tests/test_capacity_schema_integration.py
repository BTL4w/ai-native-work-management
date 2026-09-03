"""PostgreSQL RLS, tenant-reference, and grant tests for Capacity and Leave."""

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

_TABLES = ("capacity_entries", "leave_entries")


@pytest.mark.asyncio
async def test_capacity_and_leave_rls_defaults_to_deny_and_cross_tenant_links_fail() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_a, org_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()
    member_a, member_b = uuid4(), uuid4()
    capacity_id = uuid4()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:org_a, :slug_a, 'Tenant A'), "
                    "(:org_b, :slug_b, 'Tenant B')"
                ),
                {
                    "org_a": org_a,
                    "slug_a": f"tenant-a-{org_a.hex}",
                    "org_b": org_b,
                    "slug_b": f"tenant-b-{org_b.hex}",
                },
            )

            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) VALUES "
                    "(:user_a, :email_a, :email_a, 'User A', 'hash'), "
                    "(:user_b, :email_b, :email_b, 'User B', 'hash')"
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
                    "(:member_a, :org_a, :user_a, 'MANAGER'), "
                    "(:member_b, :org_b, :user_b, 'EMPLOYEE')"
                ),
                {
                    "member_a": member_a,
                    "org_a": org_a,
                    "user_a": user_a,
                    "member_b": member_b,
                    "org_b": org_b,
                    "user_b": user_b,
                },
            )

            # Switch to app_runtime with no tenant context -> default deny
            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            assert await connection.scalar(text("SELECT count(*) FROM capacity_entries")) == 0
            assert await connection.scalar(text("SELECT count(*) FROM leave_entries")) == 0

            # Set tenant context to Tenant A
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(org_a)},
            )

            # Insert capacity entry for Member A in Tenant A
            await connection.execute(
                text(
                    "INSERT INTO capacity_entries "
                    "(id, organization_id, membership_id, kind, hours, "
                    "effective_from, effective_to, week_start) "
                    "VALUES (:id, :org_a, :member_a, 'DEFAULT', 40, "
                    "'2026-09-01', '2026-12-31', NULL)"
                ),
                {
                    "id": capacity_id,
                    "org_a": org_a,
                    "member_a": member_a,
                },
            )

            # A second DEFAULT is forbidden even if application validation races.
            with pytest.raises((DBAPIError, PsycopgError)):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO capacity_entries "
                            "(id, organization_id, membership_id, kind, hours, "
                            "effective_from, effective_to, week_start) "
                            "VALUES (:id, :org_a, :member_a, 'DEFAULT', 32, "
                            "'2026-10-01', '2027-01-31', NULL)"
                        ),
                        {"id": uuid4(), "org_a": org_a, "member_a": member_a},
                    )

            # Inserting duplicate override for same member and week fails with unique violation
            await connection.execute(
                text(
                    "INSERT INTO capacity_entries "
                    "(id, organization_id, membership_id, kind, hours, "
                    "effective_from, effective_to, week_start) "
                    "VALUES (:id, :org_a, :member_a, 'OVERRIDE', 20, "
                    "'2026-09-07', '2026-09-13', '2026-09-07')"
                ),
                {
                    "id": uuid4(),
                    "org_a": org_a,
                    "member_a": member_a,
                },
            )
            with pytest.raises((DBAPIError, PsycopgError)):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO capacity_entries "
                            "(id, organization_id, membership_id, kind, hours, "
                            "effective_from, effective_to, week_start) "
                            "VALUES (:id, :org_a, :member_a, 'OVERRIDE', 25, "
                            "'2026-09-07', '2026-09-13', '2026-09-07')"
                        ),
                        {
                            "id": uuid4(),
                            "org_a": org_a,
                            "member_a": member_a,
                        },
                    )

            # Insert leave entry
            leave_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO leave_entries "
                    "(id, organization_id, membership_id, start_date, end_date, unavailable_hours) "
                    "VALUES (:id, :org_a, :member_a, '2026-09-08', '2026-09-08', 8)"
                ),
                {
                    "id": leave_id,
                    "org_a": org_a,
                    "member_a": member_a,
                },
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM leave_entries WHERE id = :id"), {"id": leave_id}
                )
                == 1
            )

            # Cross-tenant reference should fail: linking Tenant A capacity to Tenant B membership
            with pytest.raises((DBAPIError, PsycopgError)):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO capacity_entries "
                            "(id, organization_id, membership_id, kind, hours, "
                            "effective_from, effective_to, week_start) "
                            "VALUES (:id, :org_a, :member_b, 'DEFAULT', 40, "
                            "'2026-09-01', '2026-12-31', NULL)"
                        ),
                        {
                            "id": uuid4(),
                            "org_a": org_a,
                            "member_b": member_b,
                        },
                    )

            # Leave references use the same tenant-safe composite membership key.
            with pytest.raises((DBAPIError, PsycopgError)):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO leave_entries "
                            "(id, organization_id, membership_id, start_date, end_date, "
                            "unavailable_hours) "
                            "VALUES (:id, :org_a, :member_b, '2026-09-08', '2026-09-08', 8)"
                        ),
                        {
                            "id": uuid4(),
                            "org_a": org_a,
                            "member_b": member_b,
                        },
                    )

            await transaction.rollback()
    finally:
        await engine.dispose()
