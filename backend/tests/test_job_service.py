from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.planning_runs.application.ports import (
    PlanningRunRepository,
    PlanningRunTransaction,
)
from app.modules.planning_runs.domain.models import (
    OutboxEvent,
    OutboxStatus,
    PlanningRunDomainError,
    WorkflowJob,
    WorkflowJobStatus,
)

_TEST_ORG_ID = UUID("00000000-0000-0000-0000-000000000001")

def pending_outbox_event(max_attempts: int = 3) -> OutboxEvent:
    return OutboxEvent(
        id=uuid4(),
        organization_id=_TEST_ORG_ID,
        event_id=uuid4(),
        event_type="test.event",
        aggregate_type="test",
        aggregate_id=uuid4(),
        payload={"foo": "bar"},
        status=OutboxStatus.PENDING,
        attempt_count=0,
        max_attempts=max_attempts,
        last_error_code=None,
        last_error=None,
    )

class FakeJobRepository:
    def __init__(
        self, 
        jobs: list[WorkflowJob] | None = None, 
        outbox_events: list[OutboxEvent] | None = None
    ) -> None:
        self.jobs = jobs or []
        self.outbox_events = outbox_events or []
        self.completed_jobs: set[UUID] = set()
        self.failed_jobs: list[tuple[UUID, str]] = []
        self.published_events: set[UUID] = set()
        self.failed_events: list[tuple[UUID, str]] = []

    async def claim_job(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> WorkflowJob | None:
        for i, job in enumerate(self.jobs):
            if job.status == WorkflowJobStatus.QUEUED:
                job = WorkflowJob(
                    id=job.id,
                    workflow_run_id=job.workflow_run_id,
                    organization_id=job.organization_id,
                    job_type=job.job_type,
                    status=WorkflowJobStatus.RUNNING,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    available_at=job.available_at,
                    attempt_count=job.attempt_count + 1,
                    max_attempts=job.max_attempts,
                    last_error=None,
                    payload=job.payload,
                    locked_by_worker_id=worker_id,
                    lease_until=lease_until,
                )
                self.jobs[i] = job
                return job
        return None

    async def complete_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
    ) -> None:
        self.completed_jobs.add(job_id)

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_message: str,
        next_available_at: datetime,
    ) -> None:
        self.failed_jobs.append((job_id, error_message))

    async def claim_pending_outbox_events(
        self,
        *,
        organization_id: UUID,
        worker_id: str,
        limit: int,
        now: datetime,
        lease_until: datetime,
    ) -> list[OutboxEvent]:
        claimed: list[OutboxEvent] = []
        for i, event in enumerate(self.outbox_events):
            if event.organization_id == organization_id and event.status == OutboxStatus.PENDING:
                event = OutboxEvent(
                    id=event.id,
                    organization_id=event.organization_id,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    payload=event.payload,
                    status=OutboxStatus.DISPATCHING,
                    attempt_count=event.attempt_count + 1,
                    max_attempts=event.max_attempts,
                    last_error_code=None,
                    last_error=None,
                )
                self.outbox_events[i] = event
                claimed.append(event)
                if len(claimed) >= limit:
                    break
        return claimed

    async def mark_outbox_event_published(
        self,
        *,
        organization_id: UUID,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        published_at: datetime,
    ) -> None:
        self.published_events.add(event_id)

    async def record_outbox_event_failure(
        self,
        *,
        organization_id: UUID,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        error_code: str,
        error_message: str,
        next_available_at: datetime,
    ) -> None:
        for i, event in enumerate(self.outbox_events):
            if event.id == event_id:
                status = (
                    OutboxStatus.FAILED
                    if event.attempt_count >= event.max_attempts
                    else OutboxStatus.PENDING
                )
                self.outbox_events[i] = OutboxEvent(
                    id=event.id,
                    organization_id=event.organization_id,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    payload=event.payload,
                    status=status,
                    available_at=next_available_at,
                    attempt_count=event.attempt_count,
                    max_attempts=event.max_attempts,
                    last_error_code=error_code,
                    last_error=error_message,
                )
        self.failed_events.append((event_id, error_message))

    # Stubs for other methods to satisfy Protocol
    # type: ignore


class FakeJobTransaction(PlanningRunTransaction):
    def __init__(self, repo: FakeJobRepository) -> None:
        self._repo = repo

    @property
    def repository(self) -> PlanningRunRepository:
        return self._repo  # type: ignore

    @property
    def session(self) -> None:
        return None

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> "PlanningRunTransaction":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass


class FakeJobTransactionFactory:
    def __init__(self, repo: FakeJobRepository) -> None:
        self.repo = repo

    def __call__(self, context: AuthenticatedActor | UUID) -> PlanningRunTransaction:
        return FakeJobTransaction(self.repo)


def test_compute_backoff_seconds_cap() -> None:
    from app.modules.planning_runs.application.job_service import compute_backoff_seconds

    assert compute_backoff_seconds(0) == 0
    assert compute_backoff_seconds(1) == 5
    assert compute_backoff_seconds(2) == 10
    assert compute_backoff_seconds(3) == 20
    assert compute_backoff_seconds(6) == 160
    assert compute_backoff_seconds(7) == 300
    assert compute_backoff_seconds(10) == 300
    assert compute_backoff_seconds(20) == 300


@pytest.mark.asyncio
async def test_job_service_rejects_unconfigured_tenant() -> None:
    from app.modules.planning_runs.application.job_service import JobService

    factory = FakeJobTransactionFactory(FakeJobRepository())
    service = JobService(
        transaction_factory=factory,
        handlers={},
        organization_scopes={uuid4()},
    )
    with pytest.raises(PlanningRunDomainError, match="Worker organization scope violation"):
        await service.run_once(worker_id="w-1", organization_id=uuid4())


@pytest.mark.asyncio
async def test_outbox_service_rejects_unconfigured_tenant() -> None:
    from app.modules.planning_runs.application.outbox_service import (
        OutboxService,
        UnsupportedOutboxPublisher,
    )

    factory = FakeJobTransactionFactory(FakeJobRepository())
    service = OutboxService(
        transaction_factory=factory,
        publisher=UnsupportedOutboxPublisher(),
        organization_scopes={uuid4()},
    )
    with pytest.raises(PlanningRunDomainError, match="Worker organization scope violation"):
        await service.dispatch_once(worker_id="w-1", organization_id=uuid4())


@pytest.mark.asyncio
async def test_unsupported_outbox_publisher_transitions_to_failed() -> None:
    event = pending_outbox_event(max_attempts=1)
    repo = FakeJobRepository(outbox_events=[event])
    factory = FakeJobTransactionFactory(repo)

    from app.modules.planning_runs.application.outbox_service import (
        OutboxService,
        UnsupportedOutboxPublisher,
    )

    service = OutboxService(
        transaction_factory=factory,
        publisher=UnsupportedOutboxPublisher(),
        organization_scopes={_TEST_ORG_ID},
    )
    result = await service.dispatch_once(worker_id="w-1", organization_id=_TEST_ORG_ID)

    assert result is True
    # Should transition to FAILED due to max_attempts=1 and NotImplementedError
    updated = repo.outbox_events[0]
    assert updated.status == OutboxStatus.FAILED


@pytest.mark.asyncio
async def test_job_service_custom_lease_seconds() -> None:
    from app.modules.planning_runs.application.job_service import JobService

    repo = FakeJobRepository()
    factory = FakeJobTransactionFactory(repo)
    service = JobService(
        transaction_factory=factory,
        handlers={},
        organization_scopes={_TEST_ORG_ID},
        lease_seconds=120,
    )
    assert service.lease_seconds == 120
