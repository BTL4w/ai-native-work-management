from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import pytest

from work_management_ai.runtime.contracts import (
    ActorReference,
    AgentBudget,
    AgentHandoff,
    AgentId,
    ResolvedActorContext,
)
from work_management_ai.runtime.manifests import AgentManifest
from work_management_ai.runtime.policy_guard import (
    AgentBudgetExceededError,
    AgentPolicyError,
    BudgetTracker,
    PolicyGuard,
)


def _actor(
    *,
    role: Literal["ADMIN", "MANAGER", "EMPLOYEE"] = "MANAGER",
    is_active: bool = True,
) -> ResolvedActorContext:
    return ResolvedActorContext(
        membership_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        is_active=is_active,
    )


def _manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "schema_version": "1.0",
            "agent": {
                "id": "planning",
                "name": "Planning Agent",
                "version": "1.0.0",
                "owner": "work-planning",
                "activation_phase": 2,
            },
            "capabilities": ["planning.create"],
            "contracts": {
                "input": "work_management_ai.runtime.contracts.AgentHandoff",
                "output": "work_management_ai.runtime.contracts.AgentResult",
                "handoff": "work_management_ai.runtime.contracts.AgentHandoff",
            },
            "permissions": {
                "roles": ["ADMIN", "MANAGER"],
                "tenant_scope": "actor_membership",
                "risk_ceiling": "PROPOSAL_ONLY",
            },
            "runtime": {
                "workflow": "planning.v1",
                "max_iterations": 8,
                "max_tool_calls": 12,
                "max_handoffs": 0,
                "max_replans": 1,
                "timeout_seconds": 120,
                "checkpoint": "durable",
                "model_policy": "structured_reasoning",
            },
            "allowed_skills": ["create_project_plan@1"],
            "allowed_tools": ["planning.validate_draft@1"],
            "approval": {"produced_writes": "ALWAYS", "can_self_approve": False},
            "fallback": {"strategy": "MANUAL_EDITABLE_DRAFT"},
            "evaluators": ["planning_schema@1"],
        }
    )


def _handoff(current_actor: ResolvedActorContext, **overrides: object) -> AgentHandoff:
    values: dict[str, object] = {
        "orchestration_run_id": uuid4(),
        "parent_agent_run_id": uuid4(),
        "target_agent_id": AgentId.PLANNING,
        "target_agent_version": "1.0.0",
        "capability": "planning.create",
        "objective": "Create a project plan",
        "typed_input": {"brief": "Plan a conference"},
        "context_references": (),
        "actor": ActorReference(
            membership_id=current_actor.membership_id,
            organization_id=current_actor.organization_id,
        ),
        "budget": AgentBudget(
            max_iterations=4,
            max_tool_calls=3,
            max_handoffs=0,
            max_replans=1,
            timeout_seconds=60,
        ),
        "step_id": "plan-1",
        "idempotency_key": f"plan-1:{datetime.now(UTC).timestamp()}",
    }
    values.update(overrides)
    return AgentHandoff.model_validate(values)


def test_policy_rejects_employee_planning_handoff() -> None:
    employee = _actor(role="EMPLOYEE")

    with pytest.raises(AgentPolicyError, match="AGENT_ROLE_FORBIDDEN"):
        PolicyGuard().authorize_handoff(
            current_actor=employee,
            parent_agent_id=AgentId.ORCHESTRATOR,
            handoff=_handoff(employee),
            manifest=_manifest(),
        )


def test_policy_rejects_specialist_as_parent() -> None:
    manager = _actor()

    with pytest.raises(AgentPolicyError, match="ORCHESTRATOR_REQUIRED"):
        PolicyGuard().authorize_handoff(
            current_actor=manager,
            parent_agent_id=AgentId.WORK_INTELLIGENCE,
            handoff=_handoff(manager),
            manifest=_manifest(),
        )


def test_policy_rejects_tool_outside_manifest_allowlist() -> None:
    manager = _actor()

    with pytest.raises(AgentPolicyError, match="TOOL_NOT_ALLOWED"):
        PolicyGuard().authorize_handoff(
            current_actor=manager,
            parent_agent_id=AgentId.ORCHESTRATOR,
            handoff=_handoff(manager),
            manifest=_manifest(),
            requested_tool_ids=("work.delete_project@1",),
        )


def test_policy_rejects_reserved_authority_keys_at_any_input_depth() -> None:
    manager = _actor()

    with pytest.raises(AgentPolicyError, match="RESERVED_AUTHORITY_KEY"):
        PolicyGuard().authorize_handoff(
            current_actor=manager,
            parent_agent_id=AgentId.ORCHESTRATOR,
            handoff=_handoff(manager, typed_input={"request": {"approved": True}}),
            manifest=_manifest(),
        )


def test_policy_rechecks_active_actor_and_trusted_tenant_identity() -> None:
    inactive = _actor(is_active=False)
    with pytest.raises(AgentPolicyError, match="ACTOR_INACTIVE"):
        PolicyGuard().authorize_handoff(
            current_actor=inactive,
            parent_agent_id=AgentId.ORCHESTRATOR,
            handoff=_handoff(inactive),
            manifest=_manifest(),
        )

    manager = _actor()
    forged_actor = ActorReference(
        membership_id=manager.membership_id,
        organization_id=uuid4(),
    )
    with pytest.raises(AgentPolicyError, match="ACTOR_CONTEXT_MISMATCH"):
        PolicyGuard().authorize_handoff(
            current_actor=manager,
            parent_agent_id=AgentId.ORCHESTRATOR,
            handoff=_handoff(manager, actor=forged_actor),
            manifest=_manifest(),
        )


def test_budget_stops_before_iteration_or_tool_limit_is_exceeded() -> None:
    tracker = BudgetTracker(
        AgentBudget(
            max_iterations=1,
            max_tool_calls=1,
            max_handoffs=0,
            max_replans=0,
            timeout_seconds=30,
        )
    )

    tracker.start_iteration()
    with pytest.raises(AgentBudgetExceededError, match="ITERATION_BUDGET_EXHAUSTED"):
        tracker.start_iteration()
    assert tracker.iterations == 1

    tracker.start_tool_call()
    with pytest.raises(AgentBudgetExceededError, match="TOOL_BUDGET_EXHAUSTED"):
        tracker.start_tool_call()
    assert tracker.tool_calls == 1

    with pytest.raises(AgentBudgetExceededError, match="HANDOFF_BUDGET_EXHAUSTED"):
        tracker.start_handoff()
    assert tracker.handoffs == 0

    with pytest.raises(AgentBudgetExceededError, match="REPLAN_BUDGET_EXHAUSTED"):
        tracker.start_replan()
    assert tracker.replans == 0
