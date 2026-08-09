"""Task 8 approval application-service tests."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.adapters.ai_runtime import PlanningFinalizationJobHandler
from app.modules.planning_runs.application.approval_ports import (
    ApprovalDecision,
    ApprovalDecisionResult,
    CreatedBusinessIds,
)
from app.modules.planning_runs.application.approval_service import ApprovalService
from app.modules.planning_runs.application.ports import PlanningRunTransaction
from app.modules.planning_runs.domain.models import (
    Approval,
    ApprovalStatus,
    IdempotencyKeyReusedError,
    PlanningRunForbiddenError,
    Proposal,
    ProposalStaleError,
    ProposalStatus,
    WorkflowCheckpoint,
    WorkflowJob,
    WorkflowJobStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.modules.work.application.shared_commands import (
    build_project_draft,
    build_task_draft,
)


def _actor(role: MembershipRole, organization_id: UUID | None = None) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="actor@example.test",
        display_name="Actor",
        membership_id=uuid4(),
        organization_id=organization_id or uuid4(),
        organization_name="Tenant",
        role=role,
    )


class FakeApprovalRepository:
    def __init__(self) -> None:
        self.audit: list[tuple[str, str]] = []
        self.decisions: list[dict[str, object]] = []
        self.results: dict[tuple[UUID, str, str], tuple[str, ApprovalDecisionResult]] = {}
        self.business_write_count = 0
        self.model_call_count = 0
        self.error: Exception | None = None
        self.stale_calls = 0

    async def audit_rejection(self, *, action: str, reason_code: str, **_: object) -> None:
        self.audit.append((action, reason_code))

    async def decide_approval_mutation(self, **values: object) -> ApprovalDecisionResult:
        if self.error is not None:
            raise self.error
        actor = values["actor"]
        approval_id = values["approval_id"]
        idempotency_key = values["idempotency_key"]
        assert isinstance(actor, AuthenticatedActor)
        assert isinstance(approval_id, UUID)
        assert isinstance(idempotency_key, str)
        key = (actor.membership_id, f"approval.decision:{approval_id}", idempotency_key)
        fingerprint = str(values["request_fingerprint"])
        recorded = self.results.get(key)
        if recorded is not None:
            old_fingerprint, result = recorded
            if old_fingerprint != fingerprint:
                raise IdempotencyKeyReusedError
            return ApprovalDecisionResult(
                approval_id=result.approval_id,
                approval_status=result.approval_status,
                proposal_id=result.proposal_id,
                proposal_version=result.proposal_version,
                proposal_status=result.proposal_status,
                workflow_run_id=result.workflow_run_id,
                finalization_job_id=result.finalization_job_id,
                created=result.created,
                replayed=True,
            )
        self.decisions.append(values)
        decision = values["decision"]
        assert isinstance(decision, ApprovalDecision)
        created = CreatedBusinessIds()
        if decision is ApprovalDecision.APPROVE:
            created = CreatedBusinessIds(
                project_id=uuid4(),
                goal_id=uuid4(),
                milestone_ids=(uuid4(), uuid4()),
                task_ids=(uuid4(), uuid4()),
                dependency_ids=(uuid4(),),
                acceptance_criterion_ids=(uuid4(), uuid4()),
            )
            self.business_write_count += 1
        result = ApprovalDecisionResult(
            approval_id=approval_id,
            approval_status=(
                ApprovalStatus.APPROVED
                if decision is ApprovalDecision.APPROVE
                else ApprovalStatus.REJECTED
            ),
            proposal_id=uuid4(),
            proposal_version=cast(int, values["expected_proposal_version"]),
            proposal_status=(
                ProposalStatus.APPROVED
                if decision is ApprovalDecision.APPROVE
                else ProposalStatus.REJECTED
            ),
            workflow_run_id=uuid4(),
            finalization_job_id=uuid4(),
            created=created,
            replayed=False,
        )
        self.results[key] = (fingerprint, result)
        return result

    async def mark_stale_decision_attempt(self, **_: object) -> None:
        self.stale_calls += 1
        self.audit.append(("approval.decided", "PROPOSAL_STALE"))


class FakeRuntime:
    workflow_version = "1.0.0"
    verifier_version = "1.0.0"

    def validate_capability(self, message: str) -> None:
        del message

    def validate_proposal_content(self, content: dict[str, object]) -> dict[str, object]:
        return content

    def validate_proposal_deterministically(
        self,
        content: dict[str, object],
        *,
        active_membership_ids: frozenset[UUID],
    ) -> dict[str, object]:
        del content, active_membership_ids
        return {"can_approve": True, "errors": [], "warnings": []}


class FakeTransaction(AbstractAsyncContextManager["FakeTransaction"]):
    def __init__(self, repository: FakeApprovalRepository) -> None:
        self.repository = repository

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def _service(repository: FakeApprovalRepository) -> ApprovalService:
    def make_transaction(_: AuthenticatedActor) -> FakeTransaction:
        return FakeTransaction(repository)

    factory = cast(
        Callable[[AuthenticatedActor], PlanningRunTransaction],
        make_transaction,
    )
    return ApprovalService(
        transaction_factory=factory,
        runtime=FakeRuntime(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [MembershipRole.MANAGER, MembershipRole.ADMIN])
async def test_manager_and_admin_approve_exact_version(role: MembershipRole) -> None:
    repository = FakeApprovalRepository()
    current_actor = _actor(role)

    result = await _service(repository).decide(
        actor=current_actor,
        approval_id=uuid4(),
        decision=ApprovalDecision.APPROVE,
        expected_proposal_version=4,
        reason="  Reviewed graph  ",
        request_id="req-approve",
        idempotency_key="approval-approve-key",
    )

    assert result.approval_status is ApprovalStatus.APPROVED
    assert result.proposal_version == 4
    assert result.created.project_id is not None
    assert repository.decisions[0]["reason"] == "Reviewed graph"
    assert repository.business_write_count == 1
    assert repository.model_call_count == 0


@pytest.mark.asyncio
async def test_employee_decision_is_rejected_and_audited() -> None:
    repository = FakeApprovalRepository()

    with pytest.raises(PlanningRunForbiddenError):
        await _service(repository).decide(
            actor=_actor(MembershipRole.EMPLOYEE),
            approval_id=uuid4(),
            decision=ApprovalDecision.APPROVE,
            expected_proposal_version=1,
            reason=None,
            request_id="req-forbidden",
            idempotency_key="approval-employee-key",
        )

    assert repository.decisions == []
    assert repository.audit == [("approval.decided", "FORBIDDEN")]


@pytest.mark.asyncio
async def test_reject_has_zero_business_ids() -> None:
    repository = FakeApprovalRepository()

    result = await _service(repository).decide(
        actor=_actor(MembershipRole.MANAGER),
        approval_id=uuid4(),
        decision=ApprovalDecision.REJECT,
        expected_proposal_version=2,
        reason=None,
        request_id="req-reject",
        idempotency_key="approval-reject-key",
    )

    assert result.approval_status is ApprovalStatus.REJECTED
    assert result.proposal_status is ProposalStatus.REJECTED
    assert result.created == CreatedBusinessIds()
    assert repository.business_write_count == 0


@pytest.mark.asyncio
async def test_retry_returns_recorded_result_and_changed_decision_conflicts() -> None:
    repository = FakeApprovalRepository()
    current_actor = _actor(MembershipRole.MANAGER)
    approval_id = uuid4()

    async def decide(decision: ApprovalDecision) -> ApprovalDecisionResult:
        return await _service(repository).decide(
            actor=current_actor,
            approval_id=approval_id,
            decision=decision,
            expected_proposal_version=4,
            reason="reviewed",
            request_id="req-idempotency",
            idempotency_key="approval-idempotency-key",
        )

    first = await decide(ApprovalDecision.APPROVE)
    replay = await decide(ApprovalDecision.APPROVE)

    assert replay.replayed is True
    assert replay.created == first.created
    assert repository.business_write_count == 1
    with pytest.raises(IdempotencyKeyReusedError):
        await decide(ApprovalDecision.REJECT)


@pytest.mark.asyncio
async def test_reason_is_bounded_before_transaction() -> None:
    repository = FakeApprovalRepository()

    with pytest.raises(ValueError, match="reason"):
        await _service(repository).decide(
            actor=_actor(MembershipRole.MANAGER),
            approval_id=uuid4(),
            decision=ApprovalDecision.REJECT,
            expected_proposal_version=1,
            reason="x" * 1001,
            request_id="req-reason",
            idempotency_key="approval-reason-key",
        )

    assert repository.decisions == []
    assert repository.audit == [("approval.decided", "ValueError")]


@pytest.mark.asyncio
async def test_source_change_uses_safe_stale_transaction_after_rollback() -> None:
    repository = FakeApprovalRepository()
    repository.error = ProposalStaleError()

    with pytest.raises(ProposalStaleError):
        await _service(repository).decide(
            actor=_actor(MembershipRole.MANAGER),
            approval_id=uuid4(),
            decision=ApprovalDecision.APPROVE,
            expected_proposal_version=3,
            reason=None,
            request_id="req-stale",
            idempotency_key="approval-stale-key",
        )

    assert repository.stale_calls == 1
    assert repository.audit == [("approval.decided", "PROPOSAL_STALE")]


@pytest.mark.asyncio
async def test_unexpected_failure_is_audited_without_exception_text() -> None:
    repository = FakeApprovalRepository()
    repository.error = RuntimeError("private database detail")

    with pytest.raises(RuntimeError, match="private database detail"):
        await _service(repository).decide(
            actor=_actor(MembershipRole.MANAGER),
            approval_id=uuid4(),
            decision=ApprovalDecision.APPROVE,
            expected_proposal_version=3,
            reason=None,
            request_id="req-failure",
            idempotency_key="approval-failure-key",
        )

    assert repository.audit == [("approval.decided", "INTERNAL_ERROR")]


def test_shared_project_command_enforces_manual_project_normalization() -> None:
    draft = build_project_draft(name="  Conference  ", description="  Plan  ")

    assert draft.name == "Conference"
    assert draft.description == "Plan"


def test_shared_task_command_enforces_manual_task_normalization() -> None:
    project_id, membership_id = uuid4(), uuid4()
    draft = build_task_draft(
        project_id=project_id,
        milestone_id=None,
        title="  Book venue  ",
        description="  Compare options  ",
        assignee_membership_id=membership_id,
        due_date=None,
    )

    assert draft.project_id == project_id
    assert draft.title == "Book venue"
    assert draft.description == "Compare options"
    assert draft.assignee_membership_id == membership_id


class FakeFinalizationRepository:
    def __init__(
        self,
        run: WorkflowRun,
        proposal: Proposal,
        approval: Approval,
        checkpoint: WorkflowCheckpoint,
    ) -> None:
        self.run = run
        self.proposal = proposal
        self.approval = approval
        self.events: list[object] = []
        self.checkpoints: list[WorkflowCheckpoint] = [checkpoint]

    async def get_workflow_run_by_scope(self, **_: object) -> WorkflowRun:
        return self.run

    async def get_latest_checkpoint(self, **_: object) -> WorkflowCheckpoint:
        return self.checkpoints[-1]

    async def get_approval(self, **_: object) -> Approval:
        return self.approval

    async def get_proposal(self, **_: object) -> Proposal:
        return self.proposal

    async def update_workflow_run(self, *, run: WorkflowRun, **_: object) -> WorkflowRun:
        self.run = run
        return run

    async def save_checkpoint(self, *, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        self.checkpoints.append(checkpoint)
        return checkpoint

    async def append_event(self, *, event: object) -> object:
        self.events.append(event)
        return event


class FakeFinalizationTransaction:
    def __init__(self, repository: FakeFinalizationRepository) -> None:
        self.repository = repository


@pytest.mark.asyncio
async def test_graph_finalization_completes_waiting_checkpoint_without_model_call() -> None:
    current_actor = _actor(MembershipRole.MANAGER)
    run = (
        WorkflowRun.create(
            organization_id=current_actor.organization_id,
            project_id=None,
            requested_by_membership_id=current_actor.membership_id,
            workflow_name="project_planning",
            workflow_version="1.0.0",
            verifier_version="1.0.0",
            input_goal_text="Plan",
        )
        .mark_running()
        .mark_waiting_for_decision()
    )
    proposal = Proposal.create(
        organization_id=current_actor.organization_id,
        workflow_run_id=run.id,
    )
    approval = Approval.create(
        organization_id=current_actor.organization_id,
        proposal_id=proposal.id,
        proposal_version_number=1,
    )
    proposal = proposal.mark_ready_for_decision(approval.id).mark_approved()
    approval = approval.decide_approve(decided_by=current_actor.membership_id)
    checkpoint = WorkflowCheckpoint(
        id=uuid4(),
        organization_id=current_actor.organization_id,
        workflow_run_id=run.id,
        node="await_manager_decision",
        sequence=4,
        state={"stage": "WAITING_FOR_DECISION"},
    )
    repository = FakeFinalizationRepository(run, proposal, approval, checkpoint)
    job = WorkflowJob(
        id=uuid4(),
        organization_id=current_actor.organization_id,
        workflow_run_id=run.id,
        job_type="planning.finalize",
        status=WorkflowJobStatus.RUNNING,
        payload={
            "approval_id": str(approval.id),
            "proposal_id": str(proposal.id),
            "proposal_version": 1,
            "decision": "APPROVE",
            "checkpoint_sequence": 4,
        },
    )
    handler = PlanningFinalizationJobHandler()

    await handler(FakeFinalizationTransaction(repository), job)  # type: ignore[arg-type]
    await handler(FakeFinalizationTransaction(repository), job)  # type: ignore[arg-type]

    assert repository.run.status is WorkflowRunStatus.COMPLETED
    assert repository.checkpoints[-1].node == "completed"
    assert len(repository.events) == 1
