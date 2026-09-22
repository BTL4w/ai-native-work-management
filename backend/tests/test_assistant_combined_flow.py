"""Durable Project-plus-team checkpoint contract tests."""

from dataclasses import replace
from uuid import uuid4

from app.modules.assistant.application.projection_service import advance_pending_followup
from app.modules.planning_runs.domain.models import WorkflowEvent
from work_management_ai.agents.orchestrator.contracts import ExecutionPlan, PendingFollowup
from work_management_ai.runtime.contracts import AgentBudget
from work_management_ai.runtime.execution_engine import ExecutionCheckpoint


def test_pending_team_followup_round_trips_without_authorization_facts() -> None:
    value = PendingFollowup(
        planning_workflow_run_id=uuid4(),
        planning_proposal_id=uuid4(),
        planning_proposal_version=3,
        state="WAITING_PROJECT_DECISION",
    )

    payload = value.model_dump(mode="json")

    assert PendingFollowup.model_validate(payload) == value
    assert set(payload) == {
        "kind",
        "planning_workflow_run_id",
        "planning_proposal_id",
        "planning_proposal_version",
        "project_id",
        "requirement_set_id",
        "requirement_version",
        "state",
    }
    assert not {"role", "approved", "organization_id"}.intersection(payload)


def test_pending_team_followup_has_bounded_state_transitions() -> None:
    project_id = uuid4()
    value = PendingFollowup(
        planning_workflow_run_id=uuid4(),
        planning_proposal_id=uuid4(),
        planning_proposal_version=1,
        state="WAITING_PROJECT_DECISION",
    )

    assert value.mark_ready(project_id=project_id).state == "READY"
    assert value.mark_cancelled().state == "CANCELLED"
    assert value.mark_ready(project_id=project_id).mark_completed().state == "COMPLETED"


def test_durable_execution_checkpoint_persists_pending_team_followup() -> None:
    pending = PendingFollowup(
        planning_workflow_run_id=uuid4(),
        planning_proposal_id=uuid4(),
        planning_proposal_version=2,
        state="WAITING_PROJECT_DECISION",
    )
    checkpoint = ExecutionCheckpoint(
        orchestration_run_id=uuid4(),
        sequence=1,
        node="await_project_decision",
        plan=ExecutionPlan(
            objectives=("Create a project and form a team",),
            unavailable_capabilities=("test.placeholder",),
            response_language="en",
        ),
        completed_step_ids=("plan_project",),
        agent_result_ids=(),
        remaining_budget=AgentBudget(
            max_iterations=8,
            max_tool_calls=0,
            max_handoffs=6,
            max_replans=2,
            timeout_seconds=120,
        ),
        pending_followup=pending,
    )

    restored = ExecutionCheckpoint.model_validate(checkpoint.model_dump(mode="json"))

    assert restored.pending_followup == pending


def test_project_decision_advances_only_the_matching_pending_followup() -> None:
    organization_id, workflow_id, project_id = uuid4(), uuid4(), uuid4()
    proposal_id = uuid4()
    checkpoint = {
        "pending_followup": {
            "kind": "RECOMMEND_PROJECT_TEAM",
            "planning_workflow_run_id": str(workflow_id),
            "planning_proposal_id": str(proposal_id),
            "planning_proposal_version": 1,
            "state": "WAITING_PROJECT_DECISION",
        }
    }
    approved = WorkflowEvent(
        id=uuid4(),
        organization_id=organization_id,
        workflow_run_id=workflow_id,
        sequence=1,
        event_type="workflow.completed",
        public_payload={
            "decision": "APPROVE",
            "project_id": str(project_id),
            "proposal_id": str(proposal_id),
            "proposal_version": 1,
        },
    )

    ready, should_resume = advance_pending_followup(checkpoint, approved)
    rejected, should_not_resume = advance_pending_followup(
        checkpoint,
        replace(
            approved,
            public_payload={
                "decision": "REJECT",
                "proposal_id": str(proposal_id),
                "proposal_version": 1,
            },
        ),
    )

    assert ready["pending_followup"]["state"] == "READY"
    assert should_resume is True
    assert rejected["pending_followup"]["state"] == "CANCELLED"
    assert should_not_resume is False


def test_proposal_ready_binds_the_exact_pending_followup_before_decision() -> None:
    organization_id, workflow_id, proposal_id = uuid4(), uuid4(), uuid4()
    checkpoint = {
        "pending_followup": {
            "kind": "RECOMMEND_PROJECT_TEAM",
            "planning_workflow_run_id": str(workflow_id),
            "planning_proposal_id": None,
            "planning_proposal_version": None,
            "state": "WAITING_PROJECT_PROPOSAL",
        }
    }
    event = WorkflowEvent(
        id=uuid4(),
        organization_id=organization_id,
        workflow_run_id=workflow_id,
        sequence=1,
        event_type="proposal.ready",
        public_payload={"proposal_id": str(proposal_id), "version": 2},
    )

    bound, should_resume = advance_pending_followup(checkpoint, event)

    assert bound["pending_followup"]["state"] == "WAITING_PROJECT_DECISION"
    assert bound["pending_followup"]["planning_proposal_id"] == str(proposal_id)
    assert bound["pending_followup"]["planning_proposal_version"] == 2
    assert should_resume is False
