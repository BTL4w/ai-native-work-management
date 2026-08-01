"""PostgreSQL-backed Project API, audit, idempotency, and authorization tests."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import create_database_engine
from app.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 with local PostgreSQL running",
    ),
]


@pytest.mark.asyncio
async def test_project_api_is_audited_retry_safe_versioned_and_role_scoped() -> None:
    organization_id = uuid4()
    foreign_organization_id = uuid4()
    manager_user_id, employee_user_id, admin_user_id, foreign_user_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    manager_membership_id, employee_membership_id, admin_membership_id, foreign_member_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    foreign_project_id = uuid4()
    slug = f"project-api-{organization_id.hex}"
    password = "ProjectIntegration123!"
    settings = Settings(
        environment="test",
        local_auth_organization_slug=slug,
        session_cookie_name=f"project_session_{organization_id.hex}",
    )
    engine = create_database_engine(settings)

    try:
        password_hash = PasswordHash.recommended().hash(password)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:id, :slug, 'Project API Tenant'), "
                    "(:foreign_id, :foreign_slug, 'Foreign Project Tenant')"
                ),
                {
                    "id": organization_id,
                    "slug": slug,
                    "foreign_id": foreign_organization_id,
                    "foreign_slug": f"foreign-{foreign_organization_id.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) VALUES "
                    "(:manager_id, :manager_email, :manager_email, 'Manager', :hash), "
                    "(:employee_id, :employee_email, :employee_email, 'Employee', :hash), "
                    "(:admin_id, :admin_email, :admin_email, 'Admin', :hash), "
                    "(:foreign_id, :foreign_email, :foreign_email, 'Foreign Manager', :hash)"
                ),
                {
                    "manager_id": manager_user_id,
                    "manager_email": f"manager-{manager_user_id.hex}@example.test",
                    "employee_id": employee_user_id,
                    "employee_email": f"employee-{employee_user_id.hex}@example.test",
                    "admin_id": admin_user_id,
                    "admin_email": f"admin-{admin_user_id.hex}@example.test",
                    "foreign_id": foreign_user_id,
                    "foreign_email": f"foreign-{foreign_user_id.hex}@example.test",
                    "hash": password_hash,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) VALUES "
                    "(:manager_membership, :organization_id, :manager_user, 'MANAGER'), "
                    "(:employee_membership, :organization_id, :employee_user, 'EMPLOYEE'), "
                    "(:admin_membership, :organization_id, :admin_user, 'ADMIN'), "
                    "(:foreign_membership, :foreign_organization_id, :foreign_user, 'MANAGER')"
                ),
                {
                    "manager_membership": manager_membership_id,
                    "employee_membership": employee_membership_id,
                    "organization_id": organization_id,
                    "manager_user": manager_user_id,
                    "employee_user": employee_user_id,
                    "admin_membership": admin_membership_id,
                    "admin_user": admin_user_id,
                    "foreign_membership": foreign_member_id,
                    "foreign_organization_id": foreign_organization_id,
                    "foreign_user": foreign_user_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, created_by_membership_id, "
                    "updated_by_membership_id) VALUES "
                    "(:id, :organization_id, 'Foreign Project', :membership_id, :membership_id)"
                ),
                {
                    "id": foreign_project_id,
                    "organization_id": foreign_organization_id,
                    "membership_id": foreign_member_id,
                },
            )

        app = create_app(settings)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            manager_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": f"manager-{manager_user_id.hex}@example.test",
                    "password": password,
                },
            )
            assert manager_login.status_code == 200

            payload = {"name": "  Customer onboarding  ", "description": " Playbook "}
            created = await client.post(
                "/api/v1/projects",
                json=payload,
                headers={"Idempotency-Key": "create-project-key"},
            )
            replayed = await client.post(
                "/api/v1/projects",
                json=payload,
                headers={"Idempotency-Key": "create-project-key"},
            )
            reused = await client.post(
                "/api/v1/projects",
                json={"name": "Different"},
                headers={"Idempotency-Key": "create-project-key"},
            )

            assert created.status_code == 201
            project_id = created.json()["id"]
            assert created.json()["name"] == "Customer onboarding"
            assert replayed.status_code == 201
            assert replayed.json() == created.json()
            assert replayed.headers["Idempotency-Replayed"] == "true"
            assert reused.status_code == 409
            assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

            listed = await client.get("/api/v1/projects")
            fetched = await client.get(f"/api/v1/projects/{project_id}")
            assert listed.json()["total"] == 1
            assert fetched.json() == created.json()

            updated = await client.patch(
                f"/api/v1/projects/{project_id}",
                json={"description": None},
                headers={"Idempotency-Key": "update-project-key", "If-Match": '"1"'},
            )
            replayed_update = await client.patch(
                f"/api/v1/projects/{project_id}",
                json={"description": None},
                headers={"Idempotency-Key": "update-project-key", "If-Match": '"1"'},
            )
            stale = await client.patch(
                f"/api/v1/projects/{project_id}",
                json={"name": "Stale"},
                headers={"Idempotency-Key": "stale-project-key", "If-Match": '"1"'},
            )
            assert updated.status_code == 200
            assert updated.json()["description"] is None
            assert updated.json()["version"] == 2
            assert updated.headers["etag"] == '"2"'
            assert replayed_update.json() == updated.json()
            assert replayed_update.headers["Idempotency-Replayed"] == "true"
            assert stale.status_code == 412
            assert (await client.get(f"/api/v1/projects/{foreign_project_id}")).status_code == 404
            foreign_update = await client.patch(
                f"/api/v1/projects/{foreign_project_id}",
                json={"name": "Cross tenant"},
                headers={"Idempotency-Key": "foreign-project-key", "If-Match": '"1"'},
            )
            assert foreign_update.status_code == 404

            await client.post("/api/v1/auth/logout")
            employee_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": f"employee-{employee_user_id.hex}@example.test",
                    "password": password,
                },
            )
            assert employee_login.status_code == 200
            employee_list = await client.get("/api/v1/projects")
            forbidden = await client.post(
                "/api/v1/projects",
                json={"name": "Forbidden"},
                headers={"Idempotency-Key": "employee-create-key"},
            )
            assert employee_list.json()["items"] == []
            assert forbidden.status_code == 403

            await client.post("/api/v1/auth/logout")
            admin_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": f"admin-{admin_user_id.hex}@example.test",
                    "password": password,
                },
            )
            assert admin_login.status_code == 200
            admin_update = await client.patch(
                f"/api/v1/projects/{project_id}",
                json={"name": "Admin managed"},
                headers={"Idempotency-Key": "admin-project-key", "If-Match": '"2"'},
            )
            assert admin_update.status_code == 200
            assert admin_update.json()["version"] == 3

        database_engine = app.state.database_engine
        assert database_engine is not None
        await database_engine.dispose()

        async with engine.connect() as connection:
            project_count = await connection.scalar(
                text("SELECT count(*) FROM projects WHERE organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            audit = await connection.execute(
                text(
                    "SELECT action, outcome::text FROM audit_events "
                    "WHERE organization_id = :organization_id AND action LIKE 'project.%' "
                    "ORDER BY occurred_at, id"
                ),
                {"organization_id": organization_id},
            )
            assert project_count == 1
            assert [(row.action, row.outcome) for row in audit] == [
                ("project.created", "SUCCEEDED"),
                ("project.created", "REJECTED"),
                ("project.updated", "SUCCEEDED"),
                ("project.updated", "REJECTED"),
                ("project.updated", "REJECTED"),
                ("project.created", "REJECTED"),
                ("project.updated", "SUCCEEDED"),
            ]
    finally:
        async with engine.begin() as connection:
            for table in ("idempotency_records", "audit_events", "auth_sessions", "projects"):
                await connection.execute(
                    text(
                        f"DELETE FROM {table} WHERE organization_id "
                        "IN (:organization_id, :foreign_organization_id)"
                    ),
                    {
                        "organization_id": organization_id,
                        "foreign_organization_id": foreign_organization_id,
                    },
                )
            await connection.execute(
                text(
                    "DELETE FROM memberships WHERE organization_id "
                    "IN (:organization_id, :foreign_organization_id)"
                ),
                {
                    "organization_id": organization_id,
                    "foreign_organization_id": foreign_organization_id,
                },
            )
            await connection.execute(
                text(
                    "DELETE FROM users WHERE id IN "
                    "(:manager_id, :employee_id, :admin_id, :foreign_id)"
                ),
                {
                    "manager_id": manager_user_id,
                    "employee_id": employee_user_id,
                    "admin_id": admin_user_id,
                    "foreign_id": foreign_user_id,
                },
            )
            await connection.execute(
                text("DELETE FROM organizations WHERE id IN (:organization_id, :foreign_id)"),
                {"organization_id": organization_id, "foreign_id": foreign_organization_id},
            )
        await engine.dispose()
