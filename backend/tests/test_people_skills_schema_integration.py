"""PostgreSQL RLS, tenant-reference, and grant tests for People Skills."""

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

_TABLES = (
    "skills",
    "skill_versions",
    "person_skills",
    "skill_evidence",
    "work_outcome_evidence",
)


@pytest.mark.asyncio
async def test_people_skills_rls_defaults_to_deny_and_cross_tenant_links_fail() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_a, organization_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()
    manager_a, member_b = uuid4(), uuid4()
    skill_a = uuid4()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:organization_a, :slug_a, 'People Tenant A'), "
                    "(:organization_b, :slug_b, 'People Tenant B')"
                ),
                {
                    "organization_a": organization_a,
                    "slug_a": f"people-a-{organization_a.hex}",
                    "organization_b": organization_b,
                    "slug_b": f"people-b-{organization_b.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) VALUES "
                    "(:user_a, :email_a, :email_a, 'Manager A', 'hash'), "
                    "(:user_b, :email_b, :email_b, 'Member B', 'hash')"
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
                    "(:manager_a, :organization_a, :user_a, 'MANAGER'), "
                    "(:member_b, :organization_b, :user_b, 'EMPLOYEE')"
                ),
                {
                    "manager_a": manager_a,
                    "organization_a": organization_a,
                    "user_a": user_a,
                    "member_b": member_b,
                    "organization_b": organization_b,
                    "user_b": user_b,
                },
            )
            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            assert await connection.scalar(text("SELECT count(*) FROM skills")) == 0
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(organization_a)},
            )
            await connection.execute(
                text(
                    "INSERT INTO skills "
                    "(id, organization_id, name, normalized_name, active, "
                    "created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:id, :organization_id, 'Planning', 'planning', true, :actor, :actor)"
                ),
                {
                    "id": skill_a,
                    "organization_id": organization_a,
                    "actor": manager_a,
                },
            )
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(organization_b)},
            )
            assert await connection.scalar(text("SELECT count(*) FROM skills")) == 0

            await connection.begin_nested()
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        "INSERT INTO person_skills "
                        "(id, organization_id, membership_id, skill_id, level, "
                        "verified_by_membership_id, verified_at) VALUES "
                        "(:id, :organization_b, :member_b, :skill_a, 3, :member_b, now())"
                    ),
                    {
                        "id": uuid4(),
                        "organization_b": organization_b,
                        "member_b": member_b,
                        "skill_a": skill_a,
                    },
                )
            assert isinstance(error.value.orig, PsycopgError)
            assert error.value.orig.sqlstate in {"23503", "42501"}
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_people_skill_tables_force_rls_and_evidence_is_append_only() -> None:
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
            } == {table_name: (True, True) for table_name in _TABLES}

            owners = await connection.execute(
                text(
                    "SELECT tablename, tableowner FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename = ANY(:tables)"
                ),
                {"tables": list(_TABLES)},
            )
            assert {row.tablename: row.tableowner for row in owners} == {
                table_name: "migration_owner" for table_name in _TABLES
            }

            grants = await connection.execute(
                text(
                    "SELECT table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE grantee = 'app_runtime' AND table_name = ANY(:tables)"
                ),
                {"tables": list(_TABLES)},
            )
            by_table: dict[str, set[str]] = {}
            for row in grants:
                by_table.setdefault(row.table_name, set()).add(row.privilege_type)
            assert by_table == {
                "skills": {"DELETE", "INSERT", "SELECT", "UPDATE"},
                "person_skills": {"DELETE", "INSERT", "SELECT", "UPDATE"},
                "skill_versions": {"INSERT", "SELECT"},
                "skill_evidence": {"INSERT", "SELECT"},
                "work_outcome_evidence": {"INSERT", "SELECT"},
            }
            function_grants = await connection.execute(
                text(
                    "SELECT grantee, privilege_type "
                    "FROM information_schema.routine_privileges "
                    "WHERE routine_schema = 'public' "
                    "AND routine_name = 'lock_active_membership'"
                )
            )
            assert {(row.grantee, row.privilege_type) for row in function_grants} == {
                ("app_runtime", "EXECUTE"),
                ("migration_owner", "EXECUTE"),
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_every_people_skill_relation_rejects_cross_tenant_references() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_a, organization_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()
    member_a, member_b = uuid4(), uuid4()
    skill_a, person_skill_a, project_a, task_a = uuid4(), uuid4(), uuid4(), uuid4()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:organization_a, :slug_a, 'Evidence Tenant A'), "
                    "(:organization_b, :slug_b, 'Evidence Tenant B')"
                ),
                {
                    "organization_a": organization_a,
                    "slug_a": f"evidence-a-{organization_a.hex}",
                    "organization_b": organization_b,
                    "slug_b": f"evidence-b-{organization_b.hex}",
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
                    "(:member_a, :organization_a, :user_a, 'MANAGER'), "
                    "(:member_b, :organization_b, :user_b, 'MANAGER')"
                ),
                {
                    "member_a": member_a,
                    "organization_a": organization_a,
                    "user_a": user_a,
                    "member_b": member_b,
                    "organization_b": organization_b,
                    "user_b": user_b,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, created_by_membership_id, "
                    "updated_by_membership_id) VALUES "
                    "(:id, :organization_id, 'Evidence Project', :actor, :actor)"
                ),
                {"id": project_a, "organization_id": organization_a, "actor": member_a},
            )
            await connection.execute(
                text(
                    "INSERT INTO tasks "
                    "(id, organization_id, project_id, title, assignee_membership_id, status, "
                    "version, created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:id, :organization_id, :project_id, 'Evidence Task', :actor, "
                    "'DONE', 2, :actor, :actor)"
                ),
                {
                    "id": task_a,
                    "organization_id": organization_a,
                    "project_id": project_a,
                    "actor": member_a,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO skills "
                    "(id, organization_id, name, normalized_name, active, "
                    "created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:id, :organization_id, 'Evidence', 'evidence', true, :actor, :actor)"
                ),
                {"id": skill_a, "organization_id": organization_a, "actor": member_a},
            )
            await connection.execute(
                text(
                    "INSERT INTO person_skills "
                    "(id, organization_id, membership_id, skill_id, level, "
                    "verified_by_membership_id, verified_at) VALUES "
                    "(:id, :organization_id, :actor, :skill_id, 4, :actor, now())"
                ),
                {
                    "id": person_skill_a,
                    "organization_id": organization_a,
                    "actor": member_a,
                    "skill_id": skill_a,
                },
            )
            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(organization_b)},
            )

            attempts = (
                (
                    "INSERT INTO skills "
                    "(id, organization_id, name, normalized_name, active, "
                    "created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:id, :organization_a, 'Cross', :normalized, true, :member_a, :member_a)",
                    {
                        "id": uuid4(),
                        "organization_a": organization_a,
                        "normalized": f"cross-{uuid4().hex}",
                        "member_a": member_a,
                    },
                ),
                (
                    "INSERT INTO skill_versions "
                    "(id, organization_id, skill_id, version, name, normalized_name, active, "
                    "changed_by_membership_id) VALUES "
                    "(:id, :organization_b, :skill_a, 2, 'Cross', 'cross', true, :member_b)",
                    {
                        "id": uuid4(),
                        "organization_b": organization_b,
                        "skill_a": skill_a,
                        "member_b": member_b,
                    },
                ),
                (
                    "INSERT INTO person_skills "
                    "(id, organization_id, membership_id, skill_id, level, "
                    "verified_by_membership_id, verified_at) VALUES "
                    "(:id, :organization_b, :member_b, :skill_a, 3, :member_b, now())",
                    {
                        "id": uuid4(),
                        "organization_b": organization_b,
                        "member_b": member_b,
                        "skill_a": skill_a,
                    },
                ),
                (
                    "INSERT INTO skill_evidence "
                    "(id, organization_id, person_skill_id, evidence_type, summary, "
                    "source_resource_type, source_resource_id, source_task_id, occurred_at, "
                    "created_by_membership_id) VALUES "
                    "(:id, :organization_b, :person_skill_a, 'COMPLETED_TASK', 'Cross', "
                    "'task', :task_a, :task_a, now(), :member_b)",
                    {
                        "id": uuid4(),
                        "organization_b": organization_b,
                        "person_skill_a": person_skill_a,
                        "task_a": task_a,
                        "member_b": member_b,
                    },
                ),
                (
                    "INSERT INTO work_outcome_evidence "
                    "(id, organization_id, membership_id, evidence_type, summary, "
                    "source_resource_type, source_resource_id, source_task_id, "
                    "source_resource_version, observed_at, created_by_membership_id) VALUES "
                    "(:id, :organization_b, :member_b, 'COMPLETED_TASK', 'Cross', 'task', "
                    ":task_a, :task_a, 2, now(), :member_b)",
                    {
                        "id": uuid4(),
                        "organization_b": organization_b,
                        "member_b": member_b,
                        "task_a": task_a,
                    },
                ),
            )
            for statement, parameters in attempts:
                savepoint = await connection.begin_nested()
                with pytest.raises(DBAPIError) as error:
                    await connection.execute(text(statement), parameters)
                assert isinstance(error.value.orig, PsycopgError)
                assert error.value.orig.sqlstate in {"23503", "42501"}
                await savepoint.rollback()
            await transaction.rollback()
    finally:
        await engine.dispose()
