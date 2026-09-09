"""PostgreSQL RLS and append-only checks for Team Requirements."""

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
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]

_TABLES = (
    "team_requirement_sets",
    "team_requirement_versions",
    "team_requirement_items",
    "team_requirement_task_sources",
)


@pytest.mark.asyncio
async def test_team_requirement_catalog_forces_rls_and_runtime_cannot_bypass() -> None:
    engine = create_database_engine(Settings(environment="test"))
    try:
        async with engine.connect() as connection:
            flags = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:tables)"
                ),
                {"tables": list(_TABLES)},
            )
            assert {
                row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in flags
            } == {table: (True, True) for table in _TABLES}
            roles = await connection.execute(
                text("SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname = 'app_runtime'")
            )
            assert [(row.rolname, row.rolbypassrls) for row in roles] == [("app_runtime", False)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_team_requirement_history_denies_cross_tenant_reads_writes_and_mutations() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_a, org_b = uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            for table in _TABLES:
                assert await connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(org_a)},
            )
            # RLS WITH CHECK rejects all Tenant-B writes before a foreign-key dependency is reached.
            for table in _TABLES:
                with pytest.raises((DBAPIError, PsycopgError)):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(f"INSERT INTO {table} (id, organization_id) VALUES (:id, :org)"),
                            {"id": uuid4(), "org": org_b},
                        )
            triggers = await connection.execute(
                text(
                    "SELECT tgrelid::regclass::text FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgname LIKE 'team_requirement_%_append_only'"
                )
            )
            assert {row[0] for row in triggers} == {
                "team_requirement_versions",
                "team_requirement_items",
                "team_requirement_task_sources",
            }
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(org_b)},
            )
            for table in _TABLES:
                assert await connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
            await transaction.rollback()
    finally:
        await engine.dispose()
