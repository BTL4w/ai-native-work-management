"""Direct PostgreSQL tenant-isolation tests for Task tables."""

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


@pytest.mark.asyncio
async def test_task_rls_blocks_cross_tenant_references() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_a, org_b, user_a, user_b, member_a, member_b, project_a = (uuid4() for _ in range(7))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:a, :sa, 'A'), (:b, :sb, 'B')"
                ),
                {
                    "a": org_a,
                    "sa": f"task-rls-a-{org_a.hex}",
                    "b": org_b,
                    "sb": f"task-rls-b-{org_b.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) VALUES "
                    "(:a, :ea, :ea, 'A', 'hash'), (:b, :eb, :eb, 'B', 'hash')"
                ),
                {
                    "a": user_a,
                    "ea": f"{user_a.hex}@example.test",
                    "b": user_b,
                    "eb": f"{user_b.hex}@example.test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) VALUES "
                    "(:ma, :oa, :ua, 'MANAGER'), (:mb, :ob, :ub, 'EMPLOYEE')"
                ),
                {
                    "ma": member_a,
                    "oa": org_a,
                    "ua": user_a,
                    "mb": member_b,
                    "ob": org_b,
                    "ub": user_b,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, created_by_membership_id, "
                    "updated_by_membership_id) VALUES (:id, :org, 'A', :member, :member)"
                ),
                {"id": project_a, "org": org_a, "member": member_a},
            )
            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            assert await connection.scalar(text("SELECT count(*) FROM tasks")) == 0
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(org_a)},
            )
            await connection.begin_nested()
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        "INSERT INTO tasks "
                        "(id, organization_id, project_id, title, assignee_membership_id, "
                        "status, created_by_membership_id, updated_by_membership_id) VALUES "
                        "(:id, :org, :project, 'Cross', :assignee, 'TO_DO', "
                        ":creator, :creator)"
                    ),
                    {
                        "id": uuid4(),
                        "org": org_a,
                        "project": project_a,
                        "assignee": member_b,
                        "creator": member_a,
                    },
                )
            assert isinstance(error.value.orig, PsycopgError)
            assert error.value.orig.sqlstate == "23503"
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_tables_force_rls_and_transition_table_is_append_only_for_runtime() -> None:
    engine = create_database_engine(Settings(environment="test"))
    try:
        async with engine.connect() as connection:
            flags = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('tasks', 'task_status_transitions')"
                )
            )
            assert {
                row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in flags
            } == {"tasks": (True, True), "task_status_transitions": (True, True)}
            grants = await connection.execute(
                text(
                    "SELECT table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE grantee = 'app_runtime' "
                    "AND table_name IN ('tasks', 'task_status_transitions')"
                )
            )
            by_table: dict[str, set[str]] = {}
            for row in grants:
                by_table.setdefault(row.table_name, set()).add(row.privilege_type)
            assert by_table == {
                "tasks": {"SELECT", "INSERT", "UPDATE"},
                "task_status_transitions": {"SELECT", "INSERT"},
            }
    finally:
        await engine.dispose()
