"""ASGI boundary tests for the optimistic Team Requirements API."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.assignment.application.requirement_service import (
    InMemoryTeamRequirementRepository,
    TeamRequirementService,
)


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Manager",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=MembershipRole.MANAGER,
    )


def _app(
    actor: AuthenticatedActor,
    repository: InMemoryTeamRequirementRepository | None = None,
) -> FastAPI:
    repository = repository or InMemoryTeamRequirementRepository(
        project_managers={actor.membership_id}
    )
    app = create_app(
        Settings(environment="test"),
        team_requirement_service=TeamRequirementService(lambda: repository),
    )
    app.dependency_overrides[get_authenticated_actor] = lambda: actor
    return app


@pytest.mark.asyncio
async def test_post_patch_and_get_requirement_snapshot_enforce_preconditions() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    project_id = uuid4()
    headers = {"Idempotency-Key": "a" * 16}
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, repository)), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/api/v1/projects/{project_id}/team-requirements", headers=headers
        )
        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        missing = await client.patch(
            f"/api/v1/projects/{project_id}/team-requirements",
            json={"action": "confirm"},
            headers=headers,
        )
        assert missing.status_code == 428
        stale = await client.patch(
            f"/api/v1/projects/{project_id}/team-requirements",
            json={"action": "confirm"},
            headers={"Idempotency-Key": "b" * 16, "If-Match": '"99"'},
        )
        assert stale.status_code == 412
    assert repository.audit_actions.count("team_requirement.confirm.rejected") == 2


@pytest.mark.asyncio
async def test_ranking_preview_is_read_only_deterministic_and_available_to_employee() -> None:
    manager = _actor()
    employee = replace(manager, membership_id=uuid4(), role=MembershipRole.EMPLOYEE)
    repository = InMemoryTeamRequirementRepository(
        project_managers={manager.membership_id}, project_readers={employee.membership_id}
    )
    project_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=_app(manager, repository)), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/api/v1/projects/{project_id}/team-requirements",
            headers={"Idempotency-Key": "a" * 16},
        )
        assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=_app(employee, repository)), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/projects/{project_id}/team-requirements/ranking-preview"
        )

    assert response.status_code == 200
    assert response.json() == {
        "requirement_set_id": created.json()["id"],
        "requirement_version": 1,
        "policy_version": "ranking-v1",
        "origin": "DETERMINISTIC",
        "candidates": [],
        "allocations": [],
        "uncovered": [],
    }


@pytest.mark.asyncio
async def test_malformed_if_match_is_audited_before_returning() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    project_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, repository)), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                f"/api/v1/projects/{project_id}/team-requirements",
                headers={"Idempotency-Key": "a" * 16},
            )
        ).status_code == 201
        invalid = await client.patch(
            f"/api/v1/projects/{project_id}/team-requirements",
            json={"action": "confirm"},
            headers={"Idempotency-Key": "b" * 16, "If-Match": "1"},
        )

    assert invalid.status_code == 400
    assert repository.audit_actions.count("team_requirement.confirm.rejected") == 1


@pytest.mark.asyncio
async def test_missing_requirement_resolution_is_audited_as_a_patch_rejection() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, repository)), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/api/v1/projects/{uuid4()}/team-requirements",
            json={"action": "confirm"},
            headers={"Idempotency-Key": "a" * 16, "If-Match": '"1"'},
        )

    assert response.status_code == 404
    assert repository.audit_actions == ["team_requirement.confirm.rejected"]


@pytest.mark.asyncio
async def test_server_derived_post_rejects_a_body_instead_of_ignoring_it() -> None:
    actor = _actor()
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor)), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/projects/{uuid4()}/team-requirements",
            json={"items": []},
            headers={"Idempotency-Key": "a" * 16},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("role", [MembershipRole.MANAGER, MembershipRole.EMPLOYEE])
async def test_invalid_json_is_authorized_and_audited_before_body_parsing(
    method: str, role: MembershipRole
) -> None:
    actor = replace(_actor(), role=role)
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, repository)), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            f"/api/v1/projects/{uuid4()}/team-requirements",
            content="{",
            headers={"Content-Type": "application/json", "Idempotency-Key": "a" * 16},
        )
    assert response.status_code == (403 if role == MembershipRole.EMPLOYEE else 422)
    assert len(repository.audit_actions) == 1
