"""HTTP contract tests for the Phase 1 Project API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.application.ports import ProjectMutationResult, ProjectPage
from app.modules.work.domain.projects import Project, ProjectVersionMismatchError


def _actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Manager",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


def _project(actor: AuthenticatedActor, *, version: int = 1) -> Project:
    now = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    return Project(
        id=uuid4(),
        organization_id=actor.organization_id,
        name="Customer onboarding",
        description="Standardize onboarding",
        version=version,
        created_at=now,
        updated_at=now,
    )


class StubProjectService:
    def __init__(self, actor: AuthenticatedActor) -> None:
        self.project = _project(actor)
        self.last_create: dict[str, Any] | None = None

    async def list_projects(self, **_: object) -> ProjectPage:
        return ProjectPage(items=(self.project,), page=1, page_size=20, total=1)

    async def get_project(self, **_: object) -> Project:
        return self.project

    async def create_project(self, **values: Any) -> ProjectMutationResult:
        self.last_create = values
        return ProjectMutationResult(project=self.project, replayed=False)

    async def update_project(self, **values: Any) -> ProjectMutationResult:
        if values["expected_version"] != self.project.version:
            raise ProjectVersionMismatchError(self.project.version)
        return ProjectMutationResult(project=self.project, replayed=False)


def _app(actor: AuthenticatedActor, service: StubProjectService) -> FastAPI:
    app = create_app(Settings(environment="test"), project_service=service)  # type: ignore[arg-type]
    app.dependency_overrides[get_authenticated_actor] = lambda: actor
    return app


@pytest.mark.asyncio
async def test_create_project_returns_typed_resource_etag_and_request_context() -> None:
    actor = _actor()
    service = StubProjectService(actor)
    transport = ASGITransport(app=_app(actor, service))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/projects",
            json={"name": "Customer onboarding", "description": "Standardize onboarding"},
            headers={
                "Idempotency-Key": "project-create-key",
                "X-Request-ID": "project-request-1",
            },
        )

    assert response.status_code == 201
    assert response.headers["etag"] == '"1"'
    assert response.json() == {
        "id": str(service.project.id),
        "name": "Customer onboarding",
        "description": "Standardize onboarding",
        "version": 1,
        "created_at": "2026-08-01T10:00:00Z",
        "updated_at": "2026-08-01T10:00:00Z",
    }
    assert service.last_create is not None
    assert service.last_create["actor"] == actor
    assert service.last_create["request_id"] == "project-request-1"


@pytest.mark.asyncio
async def test_project_mutations_require_valid_retry_and_concurrency_headers() -> None:
    actor = _actor()
    service = StubProjectService(actor)
    transport = ASGITransport(app=_app(actor, service))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing_key = await client.post("/api/v1/projects", json={"name": "Project"})
        missing_version = await client.patch(
            f"/api/v1/projects/{service.project.id}",
            json={"name": "Updated"},
            headers={"Idempotency-Key": "project-update-key"},
        )
        stale = await client.patch(
            f"/api/v1/projects/{service.project.id}",
            json={"name": "Updated"},
            headers={"Idempotency-Key": "project-update-key", "If-Match": '"9"'},
        )

    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "VALIDATION_FAILED"
    assert missing_version.status_code == 428
    assert missing_version.json()["error"]["code"] == "PRECONDITION_REQUIRED"
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "RESOURCE_VERSION_MISMATCH"
    assert stale.json()["error"]["details"] == {"current_version": 1}


@pytest.mark.asyncio
async def test_project_create_rejects_unknown_or_invalid_business_fields() -> None:
    actor = _actor()
    service = StubProjectService(actor)
    transport = ASGITransport(app=_app(actor, service))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        unknown = await client.post(
            "/api/v1/projects",
            json={"name": "Project", "status": "ACTIVE"},
            headers={"Idempotency-Key": "project-create-key"},
        )
        empty = await client.post(
            "/api/v1/projects",
            json={"name": "   "},
            headers={"Idempotency-Key": "project-create-key"},
        )

    assert unknown.status_code == 422
    assert empty.status_code == 422
    assert service.last_create is None
