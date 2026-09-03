"""ASGI contract tests for Capacity, Leave, and Workload endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.application.ports import PeopleMutationResult
from app.modules.people_capacity.domain.availability import (
    CapacityEntry,
    CapacityKind,
    LeaveEntry,
)
from app.modules.people_capacity.domain.skills import (
    PeopleSkillConflictError,
    PeopleSkillForbiddenError,
    PeopleSkillNotFoundError,
    PeopleSkillVersionMismatchError,
)
from app.modules.people_capacity.domain.workload import WeeklyWorkload


def _actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Manager User",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Test Tenant",
        role=role,
    )


class StubCapacityService:
    """Stub simulating PeopleCapacityService availability & workload methods."""

    def __init__(self, actor: AuthenticatedActor) -> None:
        now = datetime(2026, 9, 1, tzinfo=UTC)
        self.actor = actor
        self.default_capacity = CapacityEntry(
            id=uuid4(),
            organization_id=actor.organization_id,
            membership_id=actor.membership_id,
            kind=CapacityKind.DEFAULT,
            hours=40,
            effective_from=date(2026, 9, 1),
            effective_to=date(2026, 12, 31),
            week_start=None,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.override_capacity = CapacityEntry(
            id=uuid4(),
            organization_id=actor.organization_id,
            membership_id=actor.membership_id,
            kind=CapacityKind.OVERRIDE,
            hours=24,
            effective_from=date(2026, 9, 7),
            effective_to=date(2026, 9, 13),
            week_start=date(2026, 9, 7),
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.leave_entry = LeaveEntry(
            id=uuid4(),
            organization_id=actor.organization_id,
            membership_id=actor.membership_id,
            start_date=date(2026, 9, 8),
            end_date=date(2026, 9, 8),
            unavailable_hours=8,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.weekly_workload = WeeklyWorkload(
            membership_id=actor.membership_id,
            project_week_id=uuid4(),
            effective_capacity_hours=32,
            allocated_effort_hours=16,
            residual_capacity_hours=16,
            workload_ratio=Decimal("0.5"),
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def authorize_mutation(self, **values: Any) -> None:
        self.calls.append(("authorize_mutation", values))
        if values["actor"].role is MembershipRole.EMPLOYEE:
            raise PeopleSkillForbiddenError

    async def audit_transport_rejection(self, **values: Any) -> None:
        self.calls.append(("audit_transport_rejection", values))

    async def list_capacity(self, **values: Any) -> tuple[CapacityEntry, ...]:
        self.calls.append(("list_capacity", values))
        return (self.default_capacity, self.override_capacity)

    async def get_capacity(self, *, actor: AuthenticatedActor, capacity_id: UUID) -> CapacityEntry:
        self.calls.append(("get_capacity", {"actor": actor, "capacity_id": capacity_id}))
        if capacity_id == self.default_capacity.id:
            return self.default_capacity
        if capacity_id == self.override_capacity.id:
            return self.override_capacity
        raise PeopleSkillNotFoundError

    async def upsert_capacity(self, **values: Any) -> PeopleMutationResult[CapacityEntry]:
        self.calls.append(("upsert_capacity", values))
        if values.get("hours") == 99:
            raise PeopleSkillConflictError
        replayed = values.get("idempotency_key") == "replayed-key-12345678"
        entry = (
            self.override_capacity if values.get("kind") == "OVERRIDE" else self.default_capacity
        )
        return PeopleMutationResult(resource=entry, replayed=replayed)

    async def delete_capacity(self, **values: Any) -> PeopleMutationResult[CapacityEntry]:
        self.calls.append(("delete_capacity", values))
        if values.get("expected_version") != self.default_capacity.version:
            raise PeopleSkillVersionMismatchError(self.default_capacity.version)
        return PeopleMutationResult(resource=self.default_capacity, replayed=False)

    async def list_leave(self, **values: Any) -> tuple[LeaveEntry, ...]:
        self.calls.append(("list_leave", values))
        return (self.leave_entry,)

    async def get_leave(self, *, actor: AuthenticatedActor, leave_id: UUID) -> LeaveEntry:
        self.calls.append(("get_leave", {"actor": actor, "leave_id": leave_id}))
        if leave_id == self.leave_entry.id:
            return self.leave_entry
        raise PeopleSkillNotFoundError

    async def create_leave(self, **values: Any) -> PeopleMutationResult[LeaveEntry]:
        self.calls.append(("create_leave", values))
        replayed = values.get("idempotency_key") == "replayed-key"
        return PeopleMutationResult(resource=self.leave_entry, replayed=replayed)

    async def update_leave(self, **values: Any) -> PeopleMutationResult[LeaveEntry]:
        self.calls.append(("update_leave", values))
        if values.get("expected_version") != self.leave_entry.version:
            raise PeopleSkillVersionMismatchError(self.leave_entry.version)
        return PeopleMutationResult(
            resource=LeaveEntry(
                id=self.leave_entry.id,
                organization_id=self.leave_entry.organization_id,
                membership_id=self.leave_entry.membership_id,
                start_date=values.get("start_date") or self.leave_entry.start_date,
                end_date=values.get("end_date") or self.leave_entry.end_date,
                unavailable_hours=(
                    values["unavailable_hours"]
                    if values.get("unavailable_hours") is not None
                    else self.leave_entry.unavailable_hours
                ),
                version=2,
                created_at=self.leave_entry.created_at,
                updated_at=self.leave_entry.updated_at,
            ),
            replayed=False,
        )

    async def delete_leave(self, **values: Any) -> PeopleMutationResult[LeaveEntry]:
        self.calls.append(("delete_leave", values))
        if values.get("expected_version") != self.leave_entry.version:
            raise PeopleSkillVersionMismatchError(self.leave_entry.version)
        return PeopleMutationResult(resource=self.leave_entry, replayed=False)

    async def list_weekly_workload(self, **values: Any) -> tuple[WeeklyWorkload, ...]:
        self.calls.append(("list_weekly_workload", values))
        target_id = values.get("membership_id")
        if target_id is not None and target_id != self.actor.membership_id:
            raise PeopleSkillNotFoundError
        return (self.weekly_workload,)


def _app(actor: AuthenticatedActor, service: StubCapacityService) -> FastAPI:
    app = create_app(Settings(environment="test"), people_capacity_service=service)  # type: ignore[arg-type]
    app.dependency_overrides[get_authenticated_actor] = lambda: actor
    return app


@pytest.mark.asyncio
async def test_manager_can_upsert_default_and_override_capacity() -> None:
    actor = _actor()
    service = StubCapacityService(actor)
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, service)), base_url="http://testserver"
    ) as client:
        # Create default capacity
        default_resp = await client.post(
            "/api/v1/capacity",
            json={
                "membership_id": str(actor.membership_id),
                "kind": "DEFAULT",
                "hours": 40,
            },
            headers={"Idempotency-Key": "capacity-create-default-1"},
        )
        assert default_resp.status_code == 201
        assert default_resp.headers["etag"] == '"1"'
        body = default_resp.json()
        assert body["kind"] == "DEFAULT"
        assert body["hours"] == 40

        # Create override capacity
        override_resp = await client.post(
            "/api/v1/capacity",
            json={
                "membership_id": str(actor.membership_id),
                "kind": "OVERRIDE",
                "week_start": "2026-09-07",
                "hours": 24,
            },
            headers={"Idempotency-Key": "capacity-create-override-1"},
        )
        assert override_resp.status_code == 201
        assert override_resp.json()["kind"] == "OVERRIDE"
        assert override_resp.json()["week_start"] == "2026-09-07"

        updated = await client.post(
            "/api/v1/capacity",
            json={
                "membership_id": str(actor.membership_id),
                "kind": "DEFAULT",
                "hours": 32,
            },
            headers={"Idempotency-Key": "capacity-update-default-1", "If-Match": '"1"'},
        )
        assert updated.status_code == 200


@pytest.mark.asyncio
async def test_capacity_idempotency_replay_and_conflict_handling() -> None:
    actor = _actor()
    service = StubCapacityService(actor)
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, service)), base_url="http://testserver"
    ) as client:
        # Replay
        replayed = await client.post(
            "/api/v1/capacity",
            json={
                "membership_id": str(actor.membership_id),
                "kind": "DEFAULT",
                "hours": 40,
            },
            headers={"Idempotency-Key": "replayed-key-12345678"},
        )
        assert replayed.status_code == 201
        assert replayed.headers.get("idempotency-replayed") == "true"

        # Conflict
        conflict = await client.post(
            "/api/v1/capacity",
            json={
                "membership_id": str(actor.membership_id),
                "kind": "DEFAULT",
                "hours": 99,
            },
            headers={"Idempotency-Key": "conflict-key-12345678"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_employee_cannot_mutate_capacity_or_leave() -> None:
    actor = _actor(MembershipRole.EMPLOYEE)
    service = StubCapacityService(actor)
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, service)), base_url="http://testserver"
    ) as client:
        # Employee cannot create capacity
        resp_cap = await client.post(
            "/api/v1/capacity",
            json={
                "membership_id": str(actor.membership_id),
                "kind": "DEFAULT",
                "hours": 40,
            },
            headers={"Idempotency-Key": "emp-cap-key-1"},
        )
        assert resp_cap.status_code == 403
        assert resp_cap.json()["error"]["code"] == "FORBIDDEN"

        # Employee cannot create leave
        resp_leave = await client.post(
            "/api/v1/leave",
            json={
                "membership_id": str(actor.membership_id),
                "start_date": "2026-09-08",
                "end_date": "2026-09-08",
                "unavailable_hours": 8,
            },
            headers={"Idempotency-Key": "emp-leave-key-1"},
        )
        assert resp_leave.status_code == 403
        assert resp_leave.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_leave_crud_and_optimistic_concurrency() -> None:
    actor = _actor()
    service = StubCapacityService(actor)
    async with AsyncClient(
        transport=ASGITransport(app=_app(actor, service)), base_url="http://testserver"
    ) as client:
        # Create leave
        created = await client.post(
            "/api/v1/leave",
            json={
                "membership_id": str(actor.membership_id),
                "start_date": "2026-09-08",
                "end_date": "2026-09-08",
                "unavailable_hours": 8,
            },
            headers={"Idempotency-Key": "leave-create-key-1234567"},
        )
        assert created.status_code == 201
        assert created.json()["unavailable_hours"] == 8

        updated = await client.patch(
            f"/api/v1/leave/{service.leave_entry.id}",
            json={"unavailable_hours": 4},
            headers={"Idempotency-Key": "leave-update-key-1234", "If-Match": '"1"'},
        )
        assert updated.status_code == 200
        assert updated.headers["etag"] == '"2"'
        assert updated.json()["unavailable_hours"] == 4

        # List leave
        listed = await client.get(
            "/api/v1/leave",
            params={"membership_id": str(actor.membership_id)},
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        # Delete leave with version mismatch
        mismatch = await client.delete(
            f"/api/v1/leave/{service.leave_entry.id}",
            headers={"Idempotency-Key": "leave-del-key-12345", "If-Match": '"99"'},
        )
        assert mismatch.status_code == 412
        assert mismatch.json()["error"]["code"] == "RESOURCE_VERSION_MISMATCH"

        # Delete leave with valid version
        deleted = await client.delete(
            f"/api/v1/leave/{service.leave_entry.id}",
            headers={"Idempotency-Key": "leave-del-key-12345", "If-Match": '"1"'},
        )
        assert deleted.status_code == 200


def test_openapi_exposes_complete_capacity_leave_and_workload_contracts() -> None:
    actor = _actor()
    schema = _app(actor, StubCapacityService(actor)).openapi()

    assert set(schema["paths"]["/api/v1/capacity"]) == {"get", "post"}
    assert set(schema["paths"]["/api/v1/capacity/{capacity_id}"]) == {"get", "delete"}
    assert set(schema["paths"]["/api/v1/leave"]) == {"get", "post"}
    assert set(schema["paths"]["/api/v1/leave/{leave_id}"]) == {
        "get",
        "patch",
        "delete",
    }
    assert set(schema["paths"]["/api/v1/workload"]) == {"get"}


@pytest.mark.asyncio
async def test_all_roles_can_query_permitted_workload() -> None:
    employee_actor = _actor(MembershipRole.EMPLOYEE)
    service = StubCapacityService(employee_actor)
    async with AsyncClient(
        transport=ASGITransport(app=_app(employee_actor, service)), base_url="http://testserver"
    ) as client:
        # Employee querying workload
        resp = await client.get(
            "/api/v1/workload",
            params={"week_start": "2026-09-07", "membership_id": str(employee_actor.membership_id)},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["effective_capacity_hours"] == 32
        assert items[0]["allocated_effort_hours"] == 16
        assert items[0]["residual_capacity_hours"] == 16
        assert items[0]["workload_ratio"] == "0.5"

        # Querying non-existent member
        unknown = await client.get(
            "/api/v1/workload",
            params={"week_start": "2026-09-07", "membership_id": str(uuid4())},
        )
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
