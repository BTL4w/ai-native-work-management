"""Unit tests for AI planning runs, proposal, and approval domain models."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.planning_runs.domain.models import (
    Approval,
    ApprovalStatus,
    InvalidTransitionError,
    PlanningRunDomainError,
    Proposal,
    ProposalStatus,
    WorkflowRun,
    WorkflowRunStatus,
)


def test_workflow_run_initialization_and_status_transitions() -> None:
    run_id = uuid4()
    org_id = uuid4()
    actor_id = uuid4()
    project_id = uuid4()

    run = WorkflowRun.create(
        id=run_id,
        organization_id=org_id,
        project_id=project_id,
        requested_by_membership_id=actor_id,
        workflow_name="planning",
        workflow_version="v1.0",
        verifier_version="planning-verifier-v1",
        input_goal_text="Launch marketing campaign",
    )

    assert run.id == run_id
    assert run.organization_id == org_id
    assert run.status == WorkflowRunStatus.QUEUED
    assert run.version == 1
    assert run.verifier_version == "planning-verifier-v1"

    running = run.mark_running()
    assert running.status == WorkflowRunStatus.RUNNING
    assert running.version == 2

    paused = running.mark_paused_for_approval()
    assert paused.status == WorkflowRunStatus.PAUSED_FOR_APPROVAL
    assert paused.version == 3

    completed = paused.mark_completed()
    assert completed.status == WorkflowRunStatus.COMPLETED
    assert completed.version == 4

    with pytest.raises(InvalidTransitionError):
        completed.mark_running()


def test_workflow_run_requires_non_empty_verifier_version() -> None:
    with pytest.raises(PlanningRunDomainError, match="verifier_version"):
        WorkflowRun.create(
            organization_id=uuid4(),
            project_id=uuid4(),
            requested_by_membership_id=uuid4(),
            workflow_name="planning",
            workflow_version="v1.0",
            verifier_version="   ",
            input_goal_text="Goal",
        )


def test_proposal_lifecycle_and_version_increment() -> None:
    proposal_id = uuid4()
    org_id = uuid4()
    run_id = uuid4()
    approval_id = uuid4()

    proposal = Proposal.create(
        id=proposal_id,
        organization_id=org_id,
        workflow_run_id=run_id,
        current_version_number=1,
    )
    assert proposal.status == ProposalStatus.DRAFT
    assert proposal.approval_id is None
    assert proposal.current_version_number == 1

    ready = proposal.mark_ready(approval_id=approval_id)
    assert ready.status == ProposalStatus.READY
    assert ready.approval_id == approval_id

    # Editing auto-increments version number and supersedes approval
    edited = ready.edit()
    assert edited.status == ProposalStatus.DRAFT
    assert edited.current_version_number == 2
    assert edited.superseded_approval_id == approval_id
    assert edited.approval_id is None

    new_approval_id = uuid4()
    ready_again = edited.mark_ready(approval_id=new_approval_id)
    assert ready_again.approval_id == new_approval_id

    approved = ready_again.mark_approved()
    assert approved.status == ProposalStatus.APPROVED
    assert approved.approval_id == new_approval_id

    with pytest.raises(InvalidTransitionError):
        approved.edit()


def test_proposal_mark_ready_supersedes_when_ready_and_approval_changes() -> None:
    proposal_id = uuid4()
    org_id = uuid4()
    run_id = uuid4()
    app1 = uuid4()
    app2 = uuid4()

    proposal = Proposal.create(
        id=proposal_id,
        organization_id=org_id,
        workflow_run_id=run_id,
        current_version_number=1,
    )
    ready1 = proposal.mark_ready(approval_id=app1)
    assert ready1.approval_id == app1

    # Mark ready with a new approval while already in READY status
    ready2 = ready1.mark_ready(approval_id=app2)
    assert ready2.approval_id == app2
    assert ready2.superseded_approval_id == app1


def test_approval_versioning_and_concurrency() -> None:
    approval_id = uuid4()
    org_id = uuid4()
    proposal_id = uuid4()
    decided_by = uuid4()

    approval = Approval.create(
        id=approval_id,
        organization_id=org_id,
        proposal_id=proposal_id,
        proposal_version_number=1,
    )
    assert approval.status == ApprovalStatus.PENDING
    assert approval.version == 1

    decided_at = datetime.now(UTC)
    approved = approval.decide_approve(
        decided_by=decided_by, decision_reason="Looks good", decided_at=decided_at
    )
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.version == 2
    assert approved.decided_by_membership_id == decided_by

    with pytest.raises(InvalidTransitionError):
        approved.decide_reject(
            decided_by=decided_by, decision_reason="Change mind", decided_at=decided_at
        )
