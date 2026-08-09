"""Bounded SSE replay, security and REST recovery tests."""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportUnknownMemberType=false

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.application.event_service import WorkflowEventService
from app.modules.planning_runs.domain.models import (
    PlanningRunForbiddenError,
    PlanningRunNotFoundError,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)
from tests.test_planning_run_api_integration import StubProposalService, StubRunService


def actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="actor@example.test",
        display_name="Actor",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


class EventRepository:
    def __init__(self, run: WorkflowRun, events: list[WorkflowEvent]) -> None:
        self.run = run
        self.events = events
        self.open_transactions = 0

    async def get_workflow_run(self, *, actor: AuthenticatedActor, run_id: UUID):
        if run_id != self.run.id or actor.organization_id != self.run.organization_id:
            return None
        return self.run

    async def list_events(
        self, *, actor: AuthenticatedActor, run_id: UUID, after_sequence: int = 0
    ) -> list[WorkflowEvent]:
        if await self.get_workflow_run(actor=actor, run_id=run_id) is None:
            return []
        return [event for event in self.events if event.sequence > after_sequence]


class EventTransaction(AbstractAsyncContextManager["EventTransaction"]):
    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    async def __aenter__(self) -> Self:
        self.repository.open_transactions += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.repository.open_transactions -= 1


def event(sequence: int, run: WorkflowRun) -> WorkflowEvent:
    return WorkflowEvent(
        id=uuid4(),
        organization_id=run.organization_id,
        workflow_run_id=run.id,
        sequence=sequence,
        event_type="proposal.validating" if sequence == 4 else "proposal.ready",
        public_payload={
            "proposal_id": "018f6a6a-9f5c-7b12-8c34-1234567890ab",
            "version": 2,
            "raw_prompt": "must not leak",
            "nested": {"secret": "must not leak", "safe": True},
        },
        created_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def service_for(run: WorkflowRun, events: list[WorkflowEvent]):
    repository = EventRepository(run, events)
    service = WorkflowEventService(
        transaction_factory=lambda _: EventTransaction(repository),
        heartbeat_seconds=0,
    )
    return service, repository


@pytest.mark.asyncio
async def test_sequences_after_last_event_id_are_ordered_framed_and_sanitized() -> None:
    current_actor = actor()
    run = StubRunService(current_actor).run
    run = WorkflowRun(**{field: getattr(run, field) for field in run.__dataclass_fields__})
    events = [event(sequence, run) for sequence in range(1, 6)]
    service, repository = service_for(run, events)

    frames = await service.replay(
        actor=current_actor,
        run_id=run.id,
        after_sequence=3,
    )

    assert [frame.splitlines()[0] for frame in frames] == ["id: 4", "id: 5"]
    assert "event: proposal.validating" in frames[0]
    assert 'data: {"nested":{"safe":true},"proposal_id"' in frames[0]
    assert "raw_prompt" not in "".join(frames)
    assert "secret" not in "".join(frames)
    assert repository.open_transactions == 0


@pytest.mark.asyncio
async def test_heartbeat_holds_no_transaction_and_disconnect_does_not_change_run() -> None:
    current_actor = actor()
    run = StubRunService(current_actor).run
    service, repository = service_for(run, [])
    stream = service.stream(actor=current_actor, run_id=run.id, after_sequence=0)

    frame = await anext(stream)
    await stream.aclose()

    assert frame == ": heartbeat\n\n"
    assert repository.open_transactions == 0
    assert repository.run.status is WorkflowRunStatus.QUEUED


@pytest.mark.asyncio
async def test_employee_and_cross_tenant_are_denied_before_streaming() -> None:
    owner = actor()
    run = StubRunService(owner).run
    service, _ = service_for(run, [])

    with pytest.raises(PlanningRunForbiddenError):
        await service.authorize(actor=actor(MembershipRole.EMPLOYEE), run_id=run.id)
    with pytest.raises(PlanningRunNotFoundError):
        await service.authorize(actor=actor(), run_id=run.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "same_tenant", "status_code"),
    [
        (MembershipRole.EMPLOYEE, True, 403),
        (MembershipRole.MANAGER, False, 404),
    ],
)
async def test_sse_endpoint_denies_before_response_stream_starts(
    role: MembershipRole,
    same_tenant: bool,
    status_code: int,
) -> None:
    owner = actor()
    run_service = StubRunService(owner)
    event_service, _ = service_for(run_service.run, [])
    current_actor = actor(role)
    if same_tenant:
        current_actor = replace(current_actor, organization_id=owner.organization_id)
    app = create_app(
        Settings(environment="test"),
        planning_run_service=run_service,  # type: ignore[arg-type]
        proposal_service=StubProposalService(owner),  # type: ignore[arg-type]
        workflow_event_service=event_service,
    )
    app.dependency_overrides[get_authenticated_actor] = lambda: current_actor

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/workflow-runs/{run_service.run.id}/events")

    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_terminal_sse_replay_and_rest_snapshot_recover_same_run() -> None:
    current_actor = actor()
    run_service = StubRunService(current_actor)
    run_service.run = run_service.run.mark_running().mark_failed("safe failure")
    event_service, _ = service_for(
        run_service.run,
        [event(sequence, run_service.run) for sequence in range(1, 6)],
    )
    app: FastAPI = create_app(
        Settings(environment="test"),
        planning_run_service=run_service,  # type: ignore[arg-type]
        proposal_service=StubProposalService(current_actor),  # type: ignore[arg-type]
        workflow_event_service=event_service,
    )
    app.dependency_overrides[get_authenticated_actor] = lambda: current_actor
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        streamed = await client.get(
            f"/api/v1/workflow-runs/{run_service.run.id}/events",
            headers={"Last-Event-ID": "3", "Accept": "text/event-stream"},
        )
        snapshot = await client.get(f"/api/v1/workflow-runs/{run_service.run.id}")
        invalid = await client.get(
            f"/api/v1/workflow-runs/{run_service.run.id}/events",
            headers={"Last-Event-ID": "not-a-sequence"},
        )

    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.text.count("id: ") == 2
    assert snapshot.status_code == 200
    assert snapshot.json()["id"] == str(run_service.run.id)
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_LAST_EVENT_ID"
