"""Direct PostgreSQL isolation tests for manual planning tables."""

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

PLANNING_TABLES = {
    "goals",
    "milestones",
    "task_dependencies",
    "acceptance_criteria",
}


@pytest.mark.asyncio
async def test_planning_tables_force_rls_and_runtime_has_minimum_grants() -> None:
    engine = create_database_engine(Settings(environment="test"))
    try:
        async with engine.connect() as connection:
            flags = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('goals', 'milestones', 'task_dependencies', "
                    "'acceptance_criteria')"
                )
            )
            assert {
                row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in flags
            } == {table: (True, True) for table in PLANNING_TABLES}

            grants = await connection.execute(
                text(
                    "SELECT table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE grantee = 'app_runtime' "
                    "AND table_name IN ('goals', 'milestones', 'task_dependencies', "
                    "'acceptance_criteria')"
                )
            )
            by_table: dict[str, set[str]] = {}
            for row in grants:
                by_table.setdefault(row.table_name, set()).add(row.privilege_type)
            assert by_table == {
                table: {"SELECT", "INSERT", "UPDATE", "DELETE"} for table in PLANNING_TABLES
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_milestone_reference_is_tenant_and_project_qualified() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_a, org_b, user_a, user_b, member_a, member_b = (uuid4() for _ in range(6))
    project_a, project_b, milestone_b = uuid4(), uuid4(), uuid4()
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
                    "sa": f"planning-a-{org_a.hex}",
                    "b": org_b,
                    "sb": f"planning-b-{org_b.hex}",
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
                    "(:ma, :oa, :ua, 'MANAGER'), (:mb, :ob, :ub, 'MANAGER')"
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
                    "INSERT INTO projects (id, organization_id, name, "
                    "created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:pa, :oa, 'A', :ma, :ma), (:pb, :ob, 'B', :mb, :mb)"
                ),
                {
                    "pa": project_a,
                    "oa": org_a,
                    "ma": member_a,
                    "pb": project_b,
                    "ob": org_b,
                    "mb": member_b,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO milestones (id, organization_id, project_id, name, position, "
                    "created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:id, :org, :project, 'Foreign', 1, :member, :member)"
                ),
                {"id": milestone_b, "org": org_b, "project": project_b, "member": member_b},
            )
            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            await connection.execute(
                text("SELECT set_config('app.organization_id', :value, true)"),
                {"value": str(org_a)},
            )
            await connection.begin_nested()
            with pytest.raises(DBAPIError) as error:
                await connection.execute(
                    text(
                        "INSERT INTO tasks (id, organization_id, project_id, milestone_id, title, "
                        "assignee_membership_id, status, created_by_membership_id, "
                        "updated_by_membership_id) VALUES "
                        "(:id, :org, :project, :milestone, 'Cross', :member, 'TO_DO', "
                        ":member, :member)"
                    ),
                    {
                        "id": uuid4(),
                        "org": org_a,
                        "project": project_a,
                        "milestone": milestone_b,
                        "member": member_a,
                    },
                )
            assert isinstance(error.value.orig, PsycopgError)
            assert error.value.orig.sqlstate == "23503"
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_cannot_read_foreign_planning_rows_with_or_without_tenant_context() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_a, org_b, user_b, member_b, project_b = (uuid4() for _ in range(5))
    goal_b, milestone_b, predecessor_b, successor_b, dependency_b, criterion_b = (
        uuid4() for _ in range(6)
    )
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
                    "sa": f"planning-read-a-{org_a.hex}",
                    "b": org_b,
                    "sb": f"planning-read-b-{org_b.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'B', 'hash')"
                ),
                {"id": user_b, "email": f"{user_b.hex}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, 'MANAGER')"
                ),
                {"id": member_b, "org": org_b, "user": user_b},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, "
                    "created_by_membership_id, updated_by_membership_id) "
                    "VALUES (:id, :org, 'B', :member, :member)"
                ),
                {"id": project_b, "org": org_b, "member": member_b},
            )
            await connection.execute(
                text(
                    "INSERT INTO goals (id, organization_id, project_id, title, expected_outcomes, "
                    "created_by_membership_id, updated_by_membership_id) "
                    "VALUES (:id, :org, :project, 'B goal', '[]'::jsonb, :member, :member)"
                ),
                {"id": goal_b, "org": org_b, "project": project_b, "member": member_b},
            )
            await connection.execute(
                text(
                    "INSERT INTO milestones (id, organization_id, project_id, name, position, "
                    "created_by_membership_id, updated_by_membership_id) "
                    "VALUES (:id, :org, :project, 'B milestone', 1, :member, :member)"
                ),
                {"id": milestone_b, "org": org_b, "project": project_b, "member": member_b},
            )
            for task_id, title in ((predecessor_b, "First"), (successor_b, "Second")):
                await connection.execute(
                    text(
                        "INSERT INTO tasks (id, organization_id, project_id, title, "
                        "assignee_membership_id, status, created_by_membership_id, "
                        "updated_by_membership_id) VALUES "
                        "(:id, :org, :project, :title, :member, 'TO_DO', :member, :member)"
                    ),
                    {
                        "id": task_id,
                        "org": org_b,
                        "project": project_b,
                        "title": title,
                        "member": member_b,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO task_dependencies (id, organization_id, "
                    "predecessor_task_id, successor_task_id, created_by_membership_id, "
                    "updated_by_membership_id) VALUES "
                    "(:id, :org, :predecessor, :successor, :member, :member)"
                ),
                {
                    "id": dependency_b,
                    "org": org_b,
                    "predecessor": predecessor_b,
                    "successor": successor_b,
                    "member": member_b,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO acceptance_criteria (id, organization_id, task_id, "
                    "text, position, created_by_membership_id, "
                    "updated_by_membership_id) VALUES "
                    "(:id, :org, :task, 'Done', 1, :member, :member)"
                ),
                {
                    "id": criterion_b,
                    "org": org_b,
                    "task": predecessor_b,
                    "member": member_b,
                },
            )

            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            for context in (None, org_a):
                if context is not None:
                    await connection.execute(
                        text("SELECT set_config('app.organization_id', :value, true)"),
                        {"value": str(context)},
                    )
                for table, row_id in (
                    ("goals", goal_b),
                    ("milestones", milestone_b),
                    ("task_dependencies", dependency_b),
                    ("acceptance_criteria", criterion_b),
                ):
                    visible = await connection.scalar(
                        text(f"SELECT count(*) FROM {table} WHERE id = :id"),
                        {"id": row_id},
                    )
                    assert visible == 0
            await transaction.rollback()
    finally:
        await engine.dispose()
