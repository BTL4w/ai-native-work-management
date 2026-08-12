"""Task 8 Assistant-to-Planning Tool bridge tests."""

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownArgumentType=false, reportArgumentType=false, reportAttributeAccessIssue=false

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.assistant.adapters.planning_tools import AssistantPlanningToolAdapter
from app.modules.assistant.domain.models import AgentRun
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.application.ports import (
    ProposalRevisionRequestResult,
    WorkflowRunMutationResult,
    WorkflowRunSnapshot,
)
from app.modules.planning_runs.domain.models import (
    IdempotencyKeyReusedError,
    WorkflowCheckpoint,
    WorkflowRun,
    WorkflowRunStatus,
)
from work_management_ai.runtime.contracts import ActorReference, ToolExecutionRequest


def _actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Manager",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


def _agent_run(actor: AuthenticatedActor, *, workflow_run_id: UUID | None = None) -> AgentRun:
    return AgentRun.create(
        organization_id=actor.organization_id,
        orchestration_run_id=uuid4(),
        agent_id="planning",
        agent_version="1.0.0",
        manifest_fingerprint="f" * 64,
        capability="planning.create",
        typed_input={},
        budget={},
        workflow_run_id=workflow_run_id,
    ).mark_running()


class _Resolver:
    def __init__(self, actor: AuthenticatedActor | None) -> None:
        self.actor = actor
        self.calls = 0

    async def resolve(self, *, organization_id: UUID, membership_id: UUID):
        self.calls += 1
        if (
            self.actor is None
            or self.actor.organization_id != organization_id
            or self.actor.membership_id != membership_id
        ):
            return None
        return self.actor


class _AssistantRepository:
    def __init__(
        self,
        run: AgentRun,
        turn_id: UUID,
        accepted_action: dict[str, object] | None = None,
    ) -> None:
        self.run = run
        self.turn_id = turn_id
        self.accepted_action = accepted_action
        self.link_calls = 0

    async def get_agent_run_turn_context(self, **_):
        return self.run, self.turn_id

    async def link_agent_workflow_run(self, *, workflow_run_id: UUID, **_):
        self.link_calls += 1
        if self.run.workflow_run_id not in {None, workflow_run_id}:
            raise RuntimeError("AGENT_WORKFLOW_LINK_CONFLICT")
        self.run = replace(
            self.run,
            workflow_run_id=workflow_run_id,
            projected_workflow_sequence=self.run.projected_workflow_sequence or 0,
        )
        return self.run

    async def get_accepted_planning_action(self, **_):
        return self.accepted_action


class _Transaction:
    def __init__(self, repository: object) -> None:
        self.repository = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def commit(self):
        return None


class _PlanningRuns:
    def __init__(self, actor: AuthenticatedActor) -> None:
        self.actor = actor
        self.run = WorkflowRun.create(
            organization_id=actor.organization_id,
            project_id=None,
            requested_by_membership_id=actor.membership_id,
            workflow_name="project_planning",
            workflow_version="1.0.0",
            verifier_version="1.0.0",
            input_goal_text="Plan a launch",
        )
        self.create_keys: list[str] = []
        self.resume_calls = 0
        self.checkpoint: WorkflowCheckpoint | None = None

    async def create_planning_run(self, *, idempotency_key: str, **_):
        self.create_keys.append(idempotency_key)
        return WorkflowRunMutationResult(run=self.run, replayed=len(self.create_keys) > 1)

    async def get_workflow_run_snapshot(self, **_):
        return WorkflowRunSnapshot(
            run=self.run,
            checkpoint=self.checkpoint,
            proposal=None,
            proposal_version=None,
            events=(),
        )

    async def post_manager_message(self, **_):
        self.resume_calls += 1
        self.run = self.run.mark_running()
        return WorkflowRunMutationResult(run=self.run, replayed=False)


class _Proposals:
    async def request_ai_revision(self, **values):
        return ProposalRevisionRequestResult(
            proposal_id=values["proposal_id"],
            base_version=values["expected_version"],
            workflow_run_id=uuid4(),
            revision_job_id=uuid4(),
            replayed=False,
        )


def _request(actor: AuthenticatedActor, run: AgentRun, typed_input: dict[str, object]):
    return ToolExecutionRequest(
        agent_run_id=run.id,
        tool_id="planning.manage_run",
        tool_version="1.0.0",
        call_id="planning:1",
        actor=ActorReference(
            membership_id=actor.membership_id,
            organization_id=actor.organization_id,
        ),
        typed_input=typed_input,
        idempotency_key="outer-key",
    )


@pytest.mark.asyncio
async def test_chat_create_reuses_same_planning_run_on_retry() -> None:
    actor = _actor()
    agent_run = _agent_run(actor)
    assistant = _AssistantRepository(agent_run, uuid4())
    planning = _PlanningRuns(actor)
    adapter = AssistantPlanningToolAdapter(
        actor_resolver=_Resolver(actor),
        assistant_transaction_factory=lambda _: _Transaction(assistant),
        planning_run_service=planning,
        proposal_service=_Proposals(),
    )
    request = _request(
        actor,
        agent_run,
        {"operation": "CREATE", "locale": "en", "brief": "Plan a launch"},
    )

    first = await adapter.execute(request)
    replay = await adapter.execute(request)

    assert first.status == replay.status == "SUCCEEDED"
    assert first.typed_output["workflow_run_id"] == replay.typed_output["workflow_run_id"]
    assert planning.create_keys == [
        f"assistant:{assistant.turn_id}:planning:create",
        f"assistant:{assistant.turn_id}:planning:create",
    ]
    assert assistant.run.workflow_run_id == planning.run.id


@pytest.mark.asyncio
async def test_chat_resume_requires_linked_await_manager_input_checkpoint() -> None:
    actor = _actor()
    workflow_run_id = uuid4()
    agent_run = _agent_run(actor, workflow_run_id=workflow_run_id)
    assistant = _AssistantRepository(agent_run, uuid4())
    planning = _PlanningRuns(actor)
    planning.run = replace(
        planning.run,
        id=workflow_run_id,
        status=WorkflowRunStatus.NEEDS_INPUT,
    )
    adapter = AssistantPlanningToolAdapter(
        actor_resolver=_Resolver(actor),
        assistant_transaction_factory=lambda _: _Transaction(assistant),
        planning_run_service=planning,
        proposal_service=_Proposals(),
    )
    request = _request(
        actor,
        agent_run,
        {
            "operation": "RESUME_INPUT",
            "locale": "en",
            "brief": "Continue",
            "workflow_run_id": str(workflow_run_id),
            "manager_instruction": "Budget is fixed",
        },
    )

    result = await adapter.execute(request)

    assert result.status == "REJECTED"
    assert result.safe_error_code == "PLANNING_RUN_NOT_AWAITING_INPUT"
    assert planning.resume_calls == 0

    planning.checkpoint = WorkflowCheckpoint(
        id=uuid4(),
        organization_id=actor.organization_id,
        workflow_run_id=workflow_run_id,
        node="await_manager_input",
        sequence=2,
        state={},
        created_at=datetime.now(UTC),
    )
    success = await adapter.execute(request.model_copy(update={"call_id": "planning:2"}))
    assert success.status == "SUCCEEDED"
    assert planning.resume_calls == 1

    foreign = await adapter.execute(
        _request(
            actor,
            agent_run,
            {
                "operation": "RESUME_INPUT",
                "locale": "en",
                "brief": "Continue",
                "workflow_run_id": str(uuid4()),
                "manager_instruction": "Budget is fixed",
            },
        )
    )
    assert foreign.status == "REJECTED"
    assert foreign.safe_error_code == "PLANNING_RUN_NOT_FOUND"
    assert planning.resume_calls == 1


@pytest.mark.asyncio
async def test_inactive_actor_fails_closed_before_planning_service() -> None:
    actor = _actor()
    agent_run = _agent_run(actor)
    planning = _PlanningRuns(actor)
    adapter = AssistantPlanningToolAdapter(
        actor_resolver=_Resolver(None),
        assistant_transaction_factory=lambda _: _Transaction(
            _AssistantRepository(agent_run, uuid4())
        ),
        planning_run_service=planning,
        proposal_service=_Proposals(),
    )

    result = await adapter.execute(
        _request(
            actor,
            agent_run,
            {"operation": "CREATE", "locale": "en", "brief": "Plan a launch"},
        )
    )

    assert result.status == "REJECTED"
    assert result.safe_error_code == "ACTOR_CONTEXT_UNAVAILABLE"
    assert planning.create_keys == []


@pytest.mark.asyncio
async def test_chat_revise_uses_accepted_card_proposal_and_if_match_not_model_values() -> None:
    actor = _actor()
    workflow_run_id = uuid4()
    accepted_proposal_id = uuid4()
    agent_run = _agent_run(actor)
    assistant = _AssistantRepository(
        agent_run,
        uuid4(),
        accepted_action={
            "kind": "PLANNING_REVISE",
            "proposal_id": str(accepted_proposal_id),
            "expected_version": 7,
        },
    )

    class Proposals(_Proposals):
        async def request_ai_revision(self, **values):
            assert values["proposal_id"] == accepted_proposal_id
            assert values["expected_version"] == 7
            return ProposalRevisionRequestResult(
                proposal_id=accepted_proposal_id,
                base_version=7,
                workflow_run_id=workflow_run_id,
                revision_job_id=uuid4(),
                replayed=False,
            )

    adapter = AssistantPlanningToolAdapter(
        actor_resolver=_Resolver(actor),
        assistant_transaction_factory=lambda _: _Transaction(assistant),
        planning_run_service=_PlanningRuns(actor),
        proposal_service=Proposals(),
    )
    result = await adapter.execute(
        _request(
            actor,
            agent_run,
            {
                "operation": "REVISE",
                "locale": "en",
                "brief": "Revise",
                "workflow_run_id": str(uuid4()),
                "proposal_id": str(uuid4()),
                "expected_proposal_version": 99,
                "manager_instruction": "Move the deadline",
            },
        )
    )

    assert result.status == "SUCCEEDED"
    assert result.typed_output["proposal_id"] == str(accepted_proposal_id)
    assert result.typed_output["proposal_version"] == 7
    assert assistant.run.workflow_run_id == workflow_run_id


@pytest.mark.asyncio
async def test_chat_revise_returns_structured_idempotency_conflict() -> None:
    actor = _actor()
    accepted_proposal_id = uuid4()
    agent_run = _agent_run(actor)
    assistant = _AssistantRepository(
        agent_run,
        uuid4(),
        accepted_action={
            "kind": "PLANNING_REVISE",
            "proposal_id": str(accepted_proposal_id),
            "expected_version": 2,
        },
    )

    class Proposals(_Proposals):
        async def request_ai_revision(self, **_):
            raise IdempotencyKeyReusedError

    adapter = AssistantPlanningToolAdapter(
        actor_resolver=_Resolver(actor),
        assistant_transaction_factory=lambda _: _Transaction(assistant),
        planning_run_service=_PlanningRuns(actor),
        proposal_service=Proposals(),
    )

    result = await adapter.execute(
        _request(
            actor,
            agent_run,
            {
                "operation": "REVISE",
                "locale": "en",
                "brief": "Revise",
                "workflow_run_id": str(uuid4()),
                "proposal_id": str(uuid4()),
                "expected_proposal_version": 99,
                "manager_instruction": "Change scope",
            },
        )
    )

    assert result.status == "REJECTED"
    assert result.safe_error_code == "IDEMPOTENCY_KEY_REUSED"
