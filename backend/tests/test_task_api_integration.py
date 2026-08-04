"""PostgreSQL-backed Task, assignment, member and My Tasks API tests."""

from __future__ import annotations

import os
from collections import Counter
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
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]


@pytest.mark.asyncio
async def test_task_flow_assignment_status_visibility_and_audit() -> None:
    organization_id = uuid4()
    foreign_organization_id = uuid4()
    manager_user, employee_user, other_user, admin_user, foreign_user = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    manager_member, employee_member, other_member, admin_member, foreign_member = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    foreign_project_id, foreign_task_id = uuid4(), uuid4()
    slug = f"task-api-{organization_id.hex}"
    password = "TaskIntegration123!"
    emails = {
        "manager": f"manager-{manager_user.hex}@example.test",
        "employee": f"employee-{employee_user.hex}@example.test",
        "other": f"other-{other_user.hex}@example.test",
        "admin": f"admin-{admin_user.hex}@example.test",
        "foreign": f"foreign-{foreign_user.hex}@example.test",
    }
    settings = Settings(
        environment="test",
        local_auth_organization_slug=slug,
        session_cookie_name=f"task_session_{organization_id.hex}",
    )
    engine = create_database_engine(settings)
    try:
        encoded = PasswordHash.recommended().hash(password)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:id, :slug, 'Task Tenant'), "
                    "(:foreign_id, :foreign_slug, 'Foreign Task Tenant')"
                ),
                {
                    "id": organization_id,
                    "slug": slug,
                    "foreign_id": foreign_organization_id,
                    "foreign_slug": f"foreign-task-{foreign_organization_id.hex}",
                },
            )
            for user_id, email, name in (
                (manager_user, emails["manager"], "Manager"),
                (employee_user, emails["employee"], "Employee"),
                (other_user, emails["other"], "Other"),
                (admin_user, emails["admin"], "Admin"),
                (foreign_user, emails["foreign"], "Foreign Manager"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email_normalized, email_display, display_name, password_hash) "
                        "VALUES (:id, :email, :email, :name, :hash)"
                    ),
                    {"id": user_id, "email": email, "name": name, "hash": encoded},
                )
            for member_id, user_id, role, member_organization_id in (
                (manager_member, manager_user, "MANAGER", organization_id),
                (employee_member, employee_user, "EMPLOYEE", organization_id),
                (other_member, other_user, "EMPLOYEE", organization_id),
                (admin_member, admin_user, "ADMIN", organization_id),
                (foreign_member, foreign_user, "MANAGER", foreign_organization_id),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO memberships "
                        "(id, organization_id, user_id, role) "
                        "VALUES (:id, :organization_id, :user_id, :role)"
                    ),
                    {
                        "id": member_id,
                        "organization_id": member_organization_id,
                        "user_id": user_id,
                        "role": role,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, created_by_membership_id, "
                    "updated_by_membership_id) VALUES "
                    "(:id, :organization_id, 'Foreign Task Project', :member_id, :member_id)"
                ),
                {
                    "id": foreign_project_id,
                    "organization_id": foreign_organization_id,
                    "member_id": foreign_member,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO tasks "
                    "(id, organization_id, project_id, title, assignee_membership_id, status, "
                    "created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:id, :organization_id, :project_id, 'Foreign Task', :member_id, 'TO_DO', "
                    ":member_id, :member_id)"
                ),
                {
                    "id": foreign_task_id,
                    "organization_id": foreign_organization_id,
                    "project_id": foreign_project_id,
                    "member_id": foreign_member,
                },
            )

        app = create_app(settings)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/v1/auth/login", json={"email": emails["manager"], "password": password}
                )
            ).status_code == 200
            members = await client.get("/api/v1/members")
            assert members.status_code == 200
            assert members.json()["total"] == 4

            project = await client.post(
                "/api/v1/projects",
                json={"name": "Onboarding"},
                headers={"Idempotency-Key": "task-project-create"},
            )
            assert project.status_code == 201
            project_id = project.json()["id"]

            body = {
                "project_id": project_id,
                "title": " Collect documents ",
                "description": " Checklist ",
                "assignee_membership_id": str(employee_member),
                "due_date": "2026-08-12",
            }
            created = await client.post(
                "/api/v1/tasks", json=body, headers={"Idempotency-Key": "task-create-key-01"}
            )
            replayed = await client.post(
                "/api/v1/tasks", json=body, headers={"Idempotency-Key": "task-create-key-01"}
            )
            reused = await client.post(
                "/api/v1/tasks",
                json={**body, "title": "Different"},
                headers={"Idempotency-Key": "task-create-key-01"},
            )
            assert created.status_code == 201
            assert created.json()["title"] == "Collect documents"
            assert created.json()["status"] == "TO_DO"
            assert created.json()["assignee"]["membership_id"] == str(employee_member)
            assert replayed.json() == created.json()
            assert replayed.headers["Idempotency-Replayed"] == "true"
            assert reused.status_code == 409
            assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
            task_id = created.json()["id"]

            listed = await client.get(f"/api/v1/tasks?project_id={project_id}")
            assert listed.json()["total"] == 1
            missing_version = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"due_date": None},
                headers={"Idempotency-Key": "task-missing-etag1"},
            )
            assert missing_version.status_code == 428
            updated = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"due_date": None},
                headers={"Idempotency-Key": "task-update-key-01", "If-Match": '"1"'},
            )
            replayed_update = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"due_date": None},
                headers={"Idempotency-Key": "task-update-key-01", "If-Match": '"1"'},
            )
            assert updated.status_code == 200
            assert updated.json()["due_date"] is None
            assert updated.json()["version"] == 2
            assert replayed_update.json() == updated.json()
            assert replayed_update.headers["Idempotency-Replayed"] == "true"
            stale = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"title": "Stale"},
                headers={"Idempotency-Key": "task-stale-key-001", "If-Match": '"1"'},
            )
            assert stale.status_code == 412
            assert stale.json()["error"]["details"] == {"current_version": 2}

            invalid = await client.post(
                f"/api/v1/tasks/{task_id}/status",
                json={"to_status": "DONE"},
                headers={"Idempotency-Key": "task-status-bad-01", "If-Match": '"2"'},
            )
            assert invalid.status_code == 409
            assert invalid.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

            await client.post("/api/v1/auth/logout")
            assert (
                await client.post(
                    "/api/v1/auth/login", json={"email": emails["employee"], "password": password}
                )
            ).status_code == 200
            mine = await client.get("/api/v1/my-tasks")
            visible_project = await client.get(f"/api/v1/projects/{project_id}")
            employee_create = await client.post(
                "/api/v1/tasks",
                json=body,
                headers={"Idempotency-Key": "employee-task-create"},
            )
            employee_update = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"title": "Forbidden update"},
                headers={"Idempotency-Key": "employee-task-update", "If-Match": '"2"'},
            )
            progressed = await client.post(
                f"/api/v1/tasks/{task_id}/status",
                json={"to_status": "IN_PROGRESS"},
                headers={"Idempotency-Key": "task-status-good-1", "If-Match": '"2"'},
            )
            replayed_progress = await client.post(
                f"/api/v1/tasks/{task_id}/status",
                json={"to_status": "IN_PROGRESS"},
                headers={"Idempotency-Key": "task-status-good-1", "If-Match": '"2"'},
            )
            assert mine.json()["total"] == 1
            assert visible_project.status_code == 200
            assert employee_create.status_code == 403
            assert employee_update.status_code == 403
            assert progressed.status_code == 200
            assert progressed.json()["status"] == "IN_PROGRESS"
            assert progressed.json()["version"] == 3
            assert replayed_progress.json() == progressed.json()
            assert replayed_progress.headers["Idempotency-Replayed"] == "true"
            assert (await client.get("/api/v1/members")).status_code == 403

            await client.post("/api/v1/auth/logout")
            assert (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": emails["manager"], "password": password},
                )
            ).status_code == 200
            assert (await client.get(f"/api/v1/tasks/{foreign_task_id}")).status_code == 404
            foreign_update = await client.patch(
                f"/api/v1/tasks/{foreign_task_id}",
                json={"title": "Cross tenant"},
                headers={"Idempotency-Key": "foreign-task-update", "If-Match": '"1"'},
            )
            foreign_project_create = await client.post(
                "/api/v1/tasks",
                json={**body, "project_id": str(foreign_project_id)},
                headers={"Idempotency-Key": "foreign-project-task"},
            )
            foreign_assignee_create = await client.post(
                "/api/v1/tasks",
                json={**body, "assignee_membership_id": str(foreign_member)},
                headers={"Idempotency-Key": "foreign-assignee-task"},
            )
            assert foreign_update.status_code == 404
            assert foreign_project_create.status_code == 422
            assert foreign_assignee_create.status_code == 422
            reassigned = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"assignee_membership_id": str(other_member)},
                headers={"Idempotency-Key": "task-reassign-key1", "If-Match": '"3"'},
            )
            replayed_reassignment = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"assignee_membership_id": str(other_member)},
                headers={"Idempotency-Key": "task-reassign-key1", "If-Match": '"3"'},
            )
            assert reassigned.status_code == 200
            assert reassigned.json()["assignee"]["membership_id"] == str(other_member)
            assert reassigned.json()["version"] == 4
            assert replayed_reassignment.json() == reassigned.json()
            assert replayed_reassignment.headers["Idempotency-Replayed"] == "true"

            await client.post("/api/v1/auth/logout")
            assert (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": emails["employee"], "password": password},
                )
            ).status_code == 200
            assert (await client.get(f"/api/v1/tasks/{task_id}")).status_code == 404
            assert (await client.get("/api/v1/my-tasks")).json()["items"] == []
            forbidden_status = await client.post(
                f"/api/v1/tasks/{task_id}/status",
                json={"to_status": "DONE"},
                headers={"Idempotency-Key": "task-status-other1", "If-Match": '"4"'},
            )
            assert forbidden_status.status_code == 403

            await client.post("/api/v1/auth/logout")
            assert (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": emails["other"], "password": password},
                )
            ).status_code == 200
            assert (await client.get(f"/api/v1/tasks/{task_id}")).status_code == 200
            assert (await client.get("/api/v1/my-tasks")).json()["total"] == 1

            await client.post("/api/v1/auth/logout")
            assert (
                await client.post(
                    "/api/v1/auth/login", json={"email": emails["admin"], "password": password}
                )
            ).status_code == 200
            admin_update = await client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"title": "Admin managed task"},
                headers={"Idempotency-Key": "admin-task-update", "If-Match": '"4"'},
            )
            assert admin_update.status_code == 200
            assert admin_update.json()["version"] == 5

        await app.state.database_engine.dispose()
        async with engine.connect() as connection:
            audit = await connection.execute(
                text(
                    "SELECT action, outcome::text, idempotency_key FROM audit_events "
                    "WHERE organization_id = :organization_id "
                    "AND action LIKE 'task.%' ORDER BY occurred_at, id"
                ),
                {"organization_id": organization_id},
            )
            actions = Counter((row.action, row.outcome, row.idempotency_key) for row in audit)
            assert actions == Counter(
                {
                    ("task.created", "SUCCEEDED", "task-create-key-01"): 1,
                    ("task.assigned", "SUCCEEDED", "task-create-key-01"): 1,
                    ("task.created", "REJECTED", "task-create-key-01"): 1,
                    ("task.updated", "SUCCEEDED", "task-update-key-01"): 1,
                    ("task.updated", "REJECTED", "task-stale-key-001"): 1,
                    ("task.status_changed", "REJECTED", "task-status-bad-01"): 1,
                    ("task.created", "REJECTED", "employee-task-create"): 1,
                    ("task.updated", "REJECTED", "employee-task-update"): 1,
                    ("task.status_changed", "SUCCEEDED", "task-status-good-1"): 1,
                    ("task.updated", "REJECTED", "foreign-task-update"): 1,
                    ("task.created", "REJECTED", "foreign-project-task"): 1,
                    ("task.created", "REJECTED", "foreign-assignee-task"): 1,
                    ("task.updated", "SUCCEEDED", "task-reassign-key1"): 1,
                    ("task.assigned", "SUCCEEDED", "task-reassign-key1"): 1,
                    ("task.status_changed", "REJECTED", "task-status-other1"): 1,
                    ("task.updated", "SUCCEEDED", "admin-task-update"): 1,
                }
            )
            transition_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM task_status_transitions "
                    "WHERE organization_id = :organization_id"
                ),
                {"organization_id": organization_id},
            )
            assert transition_count == 1
    finally:
        async with engine.begin() as connection:
            for table in (
                "task_status_transitions",
                "idempotency_records",
                "audit_events",
                "auth_sessions",
                "tasks",
                "projects",
            ):
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
                text("DELETE FROM users WHERE id IN (:a, :b, :c, :d, :e)"),
                {
                    "a": manager_user,
                    "b": employee_user,
                    "c": other_user,
                    "d": admin_user,
                    "e": foreign_user,
                },
            )
            await connection.execute(
                text("DELETE FROM organizations WHERE id IN (:organization_id, :foreign_id)"),
                {"organization_id": organization_id, "foreign_id": foreign_organization_id},
            )
        await engine.dispose()
