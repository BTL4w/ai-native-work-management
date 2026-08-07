"""Application ports and transaction boundaries for planning runs."""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.planning_runs.domain.models import (
    Approval,
    ContextReference,
    ModelInvocation,
    OutboxEvent,
    Proposal,
    ProposalVersion,
    WorkflowCheckpoint,
    WorkflowEvent,
    WorkflowJob,
    WorkflowRun,
)


class PlanningRunRepository(Protocol):
    """Repository port for AI planning run entities and workflow state."""

    async def create_workflow_run(
        self,
        *,
        run: WorkflowRun,
        job: WorkflowJob | None = None,
    ) -> WorkflowRun: ...

    async def get_workflow_run(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> WorkflowRun | None: ...

    async def update_workflow_run(
        self,
        *,
        actor: AuthenticatedActor,
        run: WorkflowRun,
    ) -> WorkflowRun: ...

    async def save_checkpoint(
        self,
        *,
        checkpoint: WorkflowCheckpoint,
    ) -> WorkflowCheckpoint: ...

    async def get_latest_checkpoint(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> WorkflowCheckpoint | None: ...

    async def create_proposal(
        self,
        *,
        proposal: Proposal,
        initial_version: ProposalVersion,
    ) -> Proposal: ...

    async def get_proposal(
        self,
        *,
        actor: AuthenticatedActor,
        proposal_id: UUID,
    ) -> Proposal | None: ...

    async def get_proposal_by_run_id(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> Proposal | None: ...

    async def update_proposal(
        self,
        *,
        actor: AuthenticatedActor,
        proposal: Proposal,
    ) -> Proposal: ...

    async def edit_proposal(
        self,
        *,
        actor: AuthenticatedActor,
        proposal: Proposal,
        version: ProposalVersion,
        superseded_approval: Approval,
    ) -> Proposal: ...

    async def append_proposal_version(
        self,
        *,
        version: ProposalVersion,
    ) -> ProposalVersion: ...

    async def get_proposal_version(
        self,
        *,
        actor: AuthenticatedActor,
        proposal_id: UUID,
        version_number: int,
    ) -> ProposalVersion | None: ...

    async def create_approval(
        self,
        *,
        approval: Approval,
    ) -> Approval: ...

    async def get_approval(
        self,
        *,
        actor: AuthenticatedActor,
        approval_id: UUID,
    ) -> Approval | None: ...

    async def decide_approval(
        self,
        *,
        actor: AuthenticatedActor,
        approval: Approval,
        proposal: Proposal,
    ) -> Approval: ...

    async def append_event(
        self,
        *,
        event: WorkflowEvent | None = None,
        actor: AuthenticatedActor | None = None,
        run_id: UUID | None = None,
        event_type: str | None = None,
        public_payload: dict[str, Any] | None = None,
    ) -> WorkflowEvent: ...

    async def list_events(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> list[WorkflowEvent]: ...

    async def record_model_invocation(
        self,
        *,
        invocation: ModelInvocation,
    ) -> ModelInvocation: ...

    async def add_context_reference(
        self,
        *,
        ref: ContextReference,
    ) -> ContextReference: ...

    async def enqueue_outbox_event(
        self,
        *,
        event: OutboxEvent,
        organization_id: UUID,
    ) -> OutboxEvent: ...

    async def claim_pending_outbox_events(
        self,
        *,
        organization_id: UUID,
        worker_id: str,
        limit: int,
        now: datetime,
        lease_until: datetime,
    ) -> list[OutboxEvent]: ...

    async def mark_outbox_event_published(
        self,
        *,
        organization_id: UUID,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        published_at: datetime,
    ) -> None: ...

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
    ) -> None: ...

    async def claim_job(
        self,
        *,
        organization_id: UUID | None = None,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> WorkflowJob | None: ...

    async def complete_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
    ) -> None: ...

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_message: str,
        next_available_at: datetime,
    ) -> None: ...


class PlanningRunTransaction(Protocol):
    """Context manager for atomic planning run transaction boundaries."""

    @property
    def repository(self) -> PlanningRunRepository: ...

    @property
    def session(self) -> Any: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def __aenter__(self) -> "PlanningRunTransaction": ...

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None: ...
