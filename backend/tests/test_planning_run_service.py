"""Task 7 planning-run and immutable-proposal application service tests."""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportAssignmentType=false

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.application.proposal_service import ProposalService
from app.modules.planning_runs.application.run_service import PlanningRunService
from app.modules.planning_runs.domain.models import (
    Approval,
    IdempotencyKeyReusedError,
    PlanningRunForbiddenError,
    PlanningRunNotFoundError,
    Proposal,
    ProposalStatus,
    ProposalVersion,
    ResourceVersionMismatchError,
    UnsupportedPlanningCapabilityError,
    WorkflowCheckpoint,
    WorkflowRun,
    WorkflowRunStateError,
    WorkflowRunStatus,
)


def actor(role: MembershipRole, organization_id: UUID | None = None) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="actor@example.test",
        display_name="Actor",
        membership_id=uuid4(),
        organization_id=organization_id or uuid4(),
        organization_name="Tenant",
        role=role,
    )


class FakeRuntime:
    workflow_version = "1.0.0"
    verifier_version = "1.0.0"

    def validate_capability(self, message: str) -> None:
        if "assignee recommendation" in message.casefold():
            raise UnsupportedPlanningCapabilityError

    def validate_proposal_content(self, content: dict[str, object]) -> dict[str, object]:
        if "project" not in content or "tasks" not in content:
            raise ValueError("invalid proposal")
        return content

    def validate_proposal_deterministically(
        self,
        content: dict[str, object],
        *,
        active_membership_ids: frozenset[UUID],
    ) -> dict[str, object]:
        del content, active_membership_ids
        return {
            "is_valid": True,
            "can_approve": True,
            "errors": [],
            "warnings": [],
        }


class FakeRepository:
    def __init__(self) -> None:
        self.runs: dict[UUID, WorkflowRun] = {}
        self.jobs: list[object] = []
        self.checkpoints: dict[UUID, WorkflowCheckpoint] = {}
        self.proposals: dict[UUID, Proposal] = {}
        self.versions: dict[tuple[UUID, int], ProposalVersion] = {}
        self.approvals: dict[UUID, Approval] = {}
        self.audit: list[tuple[str, str]] = []
        self.idempotency: dict[tuple[UUID, str, str], tuple[str, object]] = {}
        self.active_memberships: set[UUID] = set()
        self.fail_after_run = False
        self.business_record_count = 0

    async def audit_rejection(self, *, action: str, reason_code: str, **_: object) -> None:
        self.audit.append((action, reason_code))

    async def create_planning_run_mutation(self, **values: object):
        actor_value = values["actor"]
        run = values["run"]
        job = values["job"]
        key = (
            actor_value.membership_id,
            "planning_run.create",
            values["idempotency_key"],
        )
        existing = self.idempotency.get(key)
        if existing is not None:
            fingerprint, result = existing
            if fingerprint != values["request_fingerprint"]:
                from app.modules.planning_runs.domain.models import IdempotencyKeyReusedError

                raise IdempotencyKeyReusedError
            return type(result)(run=result.run, replayed=True)
        self.runs[run.id] = run
        if self.fail_after_run:
            raise RuntimeError("simulated atomic failure")
        self.jobs.append(job)
        self.audit.append(("planning_run.created", "SUCCEEDED"))
        from app.modules.planning_runs.application.ports import WorkflowRunMutationResult

        result = WorkflowRunMutationResult(run=run, replayed=False)
        self.idempotency[key] = (values["request_fingerprint"], result)
        return result

    async def list_workflow_runs(self, *, actor: AuthenticatedActor, limit: int):
        return tuple(
            run
            for run in list(self.runs.values())[-limit:]
            if run.organization_id == actor.organization_id
        )

    async def get_workflow_run(self, *, actor: AuthenticatedActor, run_id: UUID):
        run = self.runs.get(run_id)
        return run if run is not None and run.organization_id == actor.organization_id else None

    async def get_latest_checkpoint(self, *, actor: AuthenticatedActor, run_id: UUID):
        run = await self.get_workflow_run(actor=actor, run_id=run_id)
        return self.checkpoints.get(run_id) if run is not None else None

    async def resume_planning_run_mutation(self, **values: object):
        run = values["run"]
        key = (
            values["actor"].membership_id,
            f"planning_run.message:{run.id}",
            values["idempotency_key"],
        )
        self.runs[run.id] = run
        self.jobs.append(values["job"])
        self.audit.append(("planning_run.message_submitted", "SUCCEEDED"))
        from app.modules.planning_runs.application.ports import WorkflowRunMutationResult

        result = WorkflowRunMutationResult(run=run, replayed=False)
        self.idempotency[key] = (values["request_fingerprint"], result)
        return result

    async def find_workflow_run_mutation_replay(self, **values: object):
        key = (
            values["actor"].membership_id,
            values["operation"],
            values["idempotency_key"],
        )
        existing = self.idempotency.get(key)
        if existing is None:
            return None
        fingerprint, result = existing
        if fingerprint != values["request_fingerprint"]:
            raise IdempotencyKeyReusedError
        return type(result)(run=result.run, replayed=True)

    async def get_proposal(self, *, actor: AuthenticatedActor, proposal_id: UUID):
        proposal = self.proposals.get(proposal_id)
        return (
            proposal
            if proposal is not None and proposal.organization_id == actor.organization_id
            else None
        )

    async def get_proposal_version(
        self, *, actor: AuthenticatedActor, proposal_id: UUID, version_number: int
    ):
        proposal = await self.get_proposal(actor=actor, proposal_id=proposal_id)
        return self.versions.get((proposal_id, version_number)) if proposal else None

    async def get_approval(self, *, actor: AuthenticatedActor, approval_id: UUID):
        approval = self.approvals.get(approval_id)
        return (
            approval
            if approval is not None and approval.organization_id == actor.organization_id
            else None
        )

    async def find_invalid_active_membership_ids(
        self, *, actor: AuthenticatedActor, membership_ids: set[UUID]
    ) -> set[UUID]:
        return membership_ids - self.active_memberships

    async def edit_proposal_mutation(self, **values: object):
        proposal = values["proposal"]
        version = values["version"]
        approval = values["superseded_approval"]
        if approval is not None:
            self.approvals[approval.id] = approval
        self.proposals[proposal.id] = proposal
        self.versions[(proposal.id, version.version_number)] = version
        self.jobs.append(values["job"])
        self.audit.append(("proposal.edited", "SUCCEEDED"))
        from app.modules.planning_runs.application.ports import ProposalMutationResult

        result = ProposalMutationResult(proposal=proposal, version=version, replayed=False)
        key = (
            values["actor"].membership_id,
            f"proposal.edit:{proposal.id}",
            values["idempotency_key"],
        )
        self.idempotency[key] = (values["request_fingerprint"], result)
        return result

    async def find_proposal_mutation_replay(self, **values: object):
        key = (
            values["actor"].membership_id,
            values["operation"],
            values["idempotency_key"],
        )
        existing = self.idempotency.get(key)
        if existing is None:
            return None
        fingerprint, result = existing
        if fingerprint != values["request_fingerprint"]:
            raise IdempotencyKeyReusedError
        return type(result)(
            proposal=result.proposal,
            version=result.version,
            replayed=True,
        )


class FakeTransaction(AbstractAsyncContextManager["FakeTransaction"]):
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self._snapshot: tuple[object, ...] | None = None

    async def __aenter__(self) -> Self:
        self._snapshot = (
            dict(self.repository.runs),
            list(self.repository.jobs),
            list(self.repository.audit),
            dict(self.repository.idempotency),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None and self._snapshot is not None:
            runs, jobs, audit, idempotency = self._snapshot
            self.repository.runs = runs
            self.repository.jobs = jobs
            self.repository.audit = audit
            self.repository.idempotency = idempotency


def run_service(repository: FakeRepository) -> PlanningRunService:
    return PlanningRunService(
        transaction_factory=lambda _: FakeTransaction(repository),
        runtime=FakeRuntime(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [MembershipRole.MANAGER, MembershipRole.ADMIN])
async def test_manager_or_admin_creates_run_job_and_audit_atomically(role: MembershipRole) -> None:
    repository = FakeRepository()
    current_actor = actor(role)

    result = await run_service(repository).create_planning_run(
        actor=current_actor,
        message="  Plan a customer conference  ",
        locale="en",
        request_id="request-1",
        idempotency_key="planning-create-key",
    )

    assert result.run.project_id is None
    assert result.run.input_goal_text == "Plan a customer conference"
    assert len(repository.jobs) == 1
    assert repository.audit == [("planning_run.created", "SUCCEEDED")]


@pytest.mark.asyncio
async def test_employee_create_rejection_is_audited() -> None:
    repository = FakeRepository()

    with pytest.raises(PlanningRunForbiddenError):
        await run_service(repository).create_planning_run(
            actor=actor(MembershipRole.EMPLOYEE),
            message="Plan a conference",
            locale="en",
            request_id="request-2",
            idempotency_key="planning-create-key",
        )

    assert repository.audit == [("planning_run.created", "FORBIDDEN")]


@pytest.mark.asyncio
async def test_create_replays_same_request_and_rejects_changed_payload() -> None:
    repository = FakeRepository()
    current_actor = actor(MembershipRole.MANAGER)
    service = run_service(repository)
    values = {
        "actor": current_actor,
        "message": "Plan a conference",
        "locale": "en",
        "request_id": "request-3",
        "idempotency_key": "planning-create-key",
    }

    first = await service.create_planning_run(**values)
    replay = await service.create_planning_run(**values)

    assert replay.replayed is True
    assert replay.run.id == first.run.id
    with pytest.raises(IdempotencyKeyReusedError):
        await service.create_planning_run(**{**values, "message": "Different plan"})
    assert ("planning_run.created", "IdempotencyKeyReusedError") in repository.audit


@pytest.mark.asyncio
async def test_unsupported_future_capability_is_explicit_and_creates_no_job() -> None:
    repository = FakeRepository()

    with pytest.raises(UnsupportedPlanningCapabilityError):
        await run_service(repository).create_planning_run(
            actor=actor(MembershipRole.MANAGER),
            message="Give me an assignee recommendation",
            locale="en",
            request_id="request-4",
            idempotency_key="planning-create-key",
        )

    assert repository.jobs == []
    assert (
        "planning_run.created",
        "UnsupportedPlanningCapabilityError",
    ) in repository.audit


@pytest.mark.asyncio
async def test_atomic_failure_rolls_back_partial_run_job_and_audit() -> None:
    repository = FakeRepository()
    repository.fail_after_run = True

    with pytest.raises(RuntimeError, match="simulated atomic failure"):
        await run_service(repository).create_planning_run(
            actor=actor(MembershipRole.MANAGER),
            message="Plan a conference",
            locale="en",
            request_id="request-5",
            idempotency_key="planning-create-key",
        )

    assert repository.runs == {}
    assert repository.jobs == []
    assert repository.audit == []


@pytest.mark.asyncio
async def test_manager_message_resumes_only_matching_needs_input_checkpoint() -> None:
    repository = FakeRepository()
    current_actor = actor(MembershipRole.MANAGER)
    run = (
        WorkflowRun.create(
            organization_id=current_actor.organization_id,
            project_id=None,
            requested_by_membership_id=current_actor.membership_id,
            workflow_name="project_planning",
            workflow_version="1.0.0",
            verifier_version="1.0.0",
            input_goal_text="Plan a conference",
        )
        .mark_running()
        .mark_needs_input()
    )
    repository.runs[run.id] = run
    repository.checkpoints[run.id] = WorkflowCheckpoint(
        id=uuid4(),
        organization_id=current_actor.organization_id,
        workflow_run_id=run.id,
        node="await_manager_input",
        sequence=3,
        state={"stage": "NEEDS_INPUT"},
    )

    result = await run_service(repository).post_manager_message(
        actor=current_actor,
        run_id=run.id,
        message="Budget is 50,000 USD",
        request_id="request-6",
        idempotency_key="planning-message-key",
    )

    assert result.run.status is WorkflowRunStatus.RUNNING
    assert len(repository.jobs) == 1

    replay = await run_service(repository).post_manager_message(
        actor=current_actor,
        run_id=run.id,
        message="Budget is 50,000 USD",
        request_id="request-6-retry",
        idempotency_key="planning-message-key",
    )
    assert replay.replayed is True
    assert len(repository.jobs) == 1

    repository.runs[run.id] = result.run
    with pytest.raises(WorkflowRunStateError):
        await run_service(repository).post_manager_message(
            actor=current_actor,
            run_id=run.id,
            message="Another answer",
            request_id="request-7",
            idempotency_key="planning-message-key-2",
        )
    assert (
        "planning_run.message_submitted",
        "WorkflowRunStateError",
    ) in repository.audit


@pytest.mark.asyncio
async def test_cross_tenant_run_is_not_disclosed() -> None:
    repository = FakeRepository()
    owner = actor(MembershipRole.MANAGER)
    outsider = actor(MembershipRole.MANAGER)
    created = await run_service(repository).create_planning_run(
        actor=owner,
        message="Plan a conference",
        locale="en",
        request_id="request-8",
        idempotency_key="planning-create-key",
    )

    with pytest.raises(PlanningRunNotFoundError):
        await run_service(repository).get_workflow_run(
            actor=outsider,
            run_id=created.run.id,
        )


def proposal_content(assignee_id: UUID | None = None) -> dict[str, object]:
    return {
        "project": {"title": "Conference"},
        "tasks": [{"title": "Book venue", "assignee_membership_id": assignee_id}],
    }


@pytest.mark.asyncio
async def test_edit_v4_creates_immutable_v5_supersedes_approval_and_queues_validation() -> None:
    repository = FakeRepository()
    current_actor = actor(MembershipRole.MANAGER)
    run = WorkflowRun.create(
        organization_id=current_actor.organization_id,
        project_id=None,
        requested_by_membership_id=current_actor.membership_id,
        workflow_name="project_planning",
        workflow_version="1.0.0",
        verifier_version="1.0.0",
        input_goal_text="Plan",
    )
    approval = Approval.create(
        organization_id=current_actor.organization_id,
        proposal_id=uuid4(),
        proposal_version_number=4,
    )
    proposal = Proposal(
        id=approval.proposal_id,
        organization_id=current_actor.organization_id,
        workflow_run_id=run.id,
        status=ProposalStatus.READY_FOR_DECISION,
        current_version_number=4,
        approval_id=approval.id,
        version=7,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    old_version = ProposalVersion(
        id=uuid4(),
        organization_id=current_actor.organization_id,
        proposal_id=proposal.id,
        version_number=4,
        created_by_membership_id=current_actor.membership_id,
        content=proposal_content(),
        assumptions=[],
    )
    repository.runs[run.id] = run
    repository.proposals[proposal.id] = proposal
    repository.versions[(proposal.id, 4)] = old_version
    repository.approvals[approval.id] = approval
    service = ProposalService(
        transaction_factory=lambda _: FakeTransaction(repository), runtime=FakeRuntime()
    )

    result = await service.edit_proposal(
        actor=current_actor,
        proposal_id=proposal.id,
        expected_version=4,
        content=proposal_content(),
        request_id="request-9",
        idempotency_key="proposal-edit-key",
    )

    assert result.version.version_number == 5
    assert result.version.validation_result["can_approve"] is True
    assert result.proposal.status is ProposalStatus.DRAFT
    assert repository.versions[(proposal.id, 4)] is old_version
    assert repository.approvals[approval.id].status.value == "SUPERSEDED"
    assert len(repository.jobs) == 1
    assert repository.business_record_count == 0

    replay = await service.edit_proposal(
        actor=current_actor,
        proposal_id=proposal.id,
        expected_version=4,
        content=proposal_content(),
        request_id="request-9-retry",
        idempotency_key="proposal-edit-key",
    )
    assert replay.replayed is True
    assert len(repository.jobs) == 1


@pytest.mark.asyncio
async def test_proposal_edit_rejects_stale_version_employee_and_invalid_assignee() -> None:
    repository = FakeRepository()
    current_actor = actor(MembershipRole.MANAGER)
    proposal = Proposal.create(
        organization_id=current_actor.organization_id,
        workflow_run_id=uuid4(),
        current_version_number=4,
    )
    repository.proposals[proposal.id] = proposal
    repository.versions[(proposal.id, 4)] = ProposalVersion(
        id=uuid4(),
        organization_id=current_actor.organization_id,
        proposal_id=proposal.id,
        version_number=4,
        created_by_membership_id=current_actor.membership_id,
        content=proposal_content(),
        assumptions=[],
    )
    service = ProposalService(
        transaction_factory=lambda _: FakeTransaction(repository), runtime=FakeRuntime()
    )

    with pytest.raises(ResourceVersionMismatchError):
        await service.edit_proposal(
            actor=current_actor,
            proposal_id=proposal.id,
            expected_version=3,
            content=proposal_content(),
            request_id="request-10",
            idempotency_key="proposal-edit-key",
        )
    with pytest.raises(PlanningRunForbiddenError):
        await service.edit_proposal(
            actor=actor(MembershipRole.EMPLOYEE, current_actor.organization_id),
            proposal_id=proposal.id,
            expected_version=4,
            content=proposal_content(),
            request_id="request-11",
            idempotency_key="proposal-edit-key-2",
        )
    with pytest.raises(ValueError, match="ASSIGNEE_NOT_ALLOWED_IN_PLAN"):
        await service.edit_proposal(
            actor=current_actor,
            proposal_id=proposal.id,
            expected_version=4,
            content=proposal_content(uuid4()),
            request_id="request-12",
            idempotency_key="proposal-edit-key-3",
        )
    assert ("proposal.edited", "ResourceVersionMismatchError") in repository.audit
    assert ("proposal.edited", "FORBIDDEN") in repository.audit
    assert ("proposal.edited", "ValueError") in repository.audit
