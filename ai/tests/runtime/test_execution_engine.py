# pyright: reportUnknownParameterType=false, reportMissingParameterType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false

from uuid import UUID, uuid4

import pytest

from work_management_ai.agents.orchestrator.contracts import (
    ActiveConversationContext,
    ExecutionPlan,
    OrchestratorInput,
    OrchestratorOutput,
    OrchestratorStatus,
    PendingFollowup,
)
from work_management_ai.runtime.contracts import (
    ActorReference,
    AgentBudget,
    AgentHandoff,
    AgentId,
    AgentResult,
    AgentRunStatus,
    CapabilityUnavailableResponseBlock,
)
from work_management_ai.runtime.execution_engine import (
    AgentExecutionEngine,
    DurableSpecialistRunner,
    ExecutionCheckpoint,
    RecordedAgentRun,
)


class Recorder:
    def __init__(self) -> None:
        self.checkpoints = []
        self.blocks = []

    async def load_checkpoint(self, orchestration_run_id: UUID) -> ExecutionCheckpoint | None:
        self.loaded_id = orchestration_run_id
        return None

    async def start_agent_run(self, handoff: AgentHandoff) -> RecordedAgentRun:
        raise AssertionError("not used")

    async def finish_agent_run(self, run_id: UUID, result: AgentResult) -> None:
        raise AssertionError("not used")

    async def save_checkpoint(self, checkpoint):
        self.checkpoints.append(checkpoint)

    async def append_public_blocks(self, conversation_id, turn_id, blocks, dedupe_key):
        self.blocks.append((blocks, dedupe_key))


class Orchestrator:
    async def run_turn(self, value):
        plan = ExecutionPlan(
            objectives=("unavailable",),
            unavailable_capabilities=("risk.read",),
            response_language="en",
        )
        block = CapabilityUnavailableResponseBlock(
            capability="risk.read", message_key="assistant.unavailable"
        )
        return OrchestratorOutput(
            execution_plan=plan,
            agent_results=(),
            blocks=(block,),
            completed_step_ids=(),
            status=OrchestratorStatus.COMPLETED,
            stop_reason="CAPABILITY_UNAVAILABLE",
            replans_used=0,
            model_refs=(),
        )


@pytest.mark.asyncio
async def test_completed_agent_step_replays_without_second_harness_call() -> None:
    result = AgentResult(
        agent_id=AgentId.WORK_INTELLIGENCE,
        agent_version="1.0.0",
        status=AgentRunStatus.COMPLETED,
        typed_output={"answer": "recorded"},
        stop_reason="COMPLETED",
    )
    handoff = AgentHandoff(
        orchestration_run_id=uuid4(),
        parent_agent_run_id=uuid4(),
        target_agent_id=AgentId.WORK_INTELLIGENCE,
        target_agent_version="1.0.0",
        capability="work.answer_question",
        objective="answer",
        typed_input={},
        context_references=(),
        actor=ActorReference(membership_id=uuid4(), organization_id=uuid4()),
        budget=AgentBudget(max_iterations=2, max_tool_calls=1, timeout_seconds=10),
        step_id="answer",
        idempotency_key="step-answer",
    )

    class ReplayRecorder(Recorder):
        async def start_agent_run(self, handoff: AgentHandoff) -> RecordedAgentRun:
            assert handoff.step_id == "answer"
            return RecordedAgentRun(
                id=uuid4(), status=AgentRunStatus.COMPLETED, replayed_result=result
            )

    class Harness:
        async def run(self, handoff: AgentHandoff) -> AgentResult:
            raise AssertionError("completed Agent Run must replay")

    replayed = await DurableSpecialistRunner(
        recorder=ReplayRecorder(), harnesses={AgentId.WORK_INTELLIGENCE: Harness()}
    ).run_specialist(handoff)

    assert replayed == result


@pytest.mark.asyncio
async def test_execution_engine_persists_terminal_checkpoint_and_public_blocks() -> None:
    value = OrchestratorInput(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        message="risk",
        locale="en",
        actor=ActorReference(membership_id=uuid4(), organization_id=uuid4()),
        active_context=ActiveConversationContext(recent_messages=()),
    )
    recorder = Recorder()
    orchestration_run_id = uuid4()
    output = await AgentExecutionEngine(Orchestrator()).execute(
        orchestration_run_id=orchestration_run_id,
        value=value,
        recorder=recorder,
    )
    assert output.stop_reason == "CAPABILITY_UNAVAILABLE"
    assert recorder.loaded_id == orchestration_run_id
    assert recorder.checkpoints[0].orchestration_run_id == orchestration_run_id
    assert recorder.checkpoints[0].node == "terminal"
    assert recorder.blocks[0][1] == f"assistant:{value.turn_id}:terminal"


@pytest.mark.asyncio
async def test_team_requirement_retry_reuses_the_same_terminal_dedupe_key() -> None:
    value = OrchestratorInput(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        message="Create the team",
        locale="en",
        actor=ActorReference(membership_id=uuid4(), organization_id=uuid4()),
        active_context=ActiveConversationContext(recent_messages=()),
    )
    workflow_id, project_id, requirement_set_id = uuid4(), uuid4(), uuid4()
    pending = PendingFollowup(
        planning_workflow_run_id=workflow_id,
        planning_proposal_id=uuid4(),
        planning_proposal_version=1,
        project_id=project_id,
        state="READY",
    )
    plan = ExecutionPlan(
        objectives=("Recommend a team",),
        unavailable_capabilities=("test.placeholder",),
        response_language="en",
    )
    result = AgentResult(
        agent_id=AgentId.ASSIGNMENT,
        agent_version="1.0.0",
        status=AgentRunStatus.AWAITING_HUMAN,
        typed_output={
            "deterministic_result": {
                "kind": "team_requirements_pending",
                "project_id": str(project_id),
                "requirement_set_id": str(requirement_set_id),
                "requirement_version": 2,
            }
        },
        stop_reason="TEAM_REQUIREMENTS_CONFIRMATION_REQUIRED",
    )

    class PendingOrchestrator:
        final = False

        async def run_turn(self, value):
            current_result = result
            if self.final:
                current_result = AgentResult(
                    agent_id=AgentId.ASSIGNMENT,
                    agent_version="1.0.0",
                    status=AgentRunStatus.COMPLETED,
                    typed_output={
                        "deterministic_result": {
                            "kind": "team_recommendation",
                            "project_id": str(project_id),
                            "recommendation_id": str(uuid4()),
                            "version": 1,
                        }
                    },
                    stop_reason="COMPLETED",
                )
            return OrchestratorOutput(
                execution_plan=plan,
                agent_results=(current_result,),
                blocks=(
                    CapabilityUnavailableResponseBlock(
                        capability="team.requirements", message_key="confirmation.required"
                    ),
                ),
                completed_step_ids=("recommend_team",),
                status=OrchestratorStatus.AWAITING_HUMAN,
                stop_reason="AWAITING_HUMAN",
                replans_used=0,
                model_refs=(),
            )

    class RetryRecorder(Recorder):
        def __init__(self) -> None:
            super().__init__()
            self.current: ExecutionCheckpoint = ExecutionCheckpoint(
                orchestration_run_id=workflow_id,
                sequence=1,
                node="terminal",
                plan=plan,
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

        async def load_checkpoint(self, orchestration_run_id: UUID) -> ExecutionCheckpoint:
            del orchestration_run_id
            return self.current

        async def save_checkpoint(self, checkpoint):
            await super().save_checkpoint(checkpoint)
            self.current = checkpoint

    recorder = RetryRecorder()
    orchestrator = PendingOrchestrator()
    engine = AgentExecutionEngine(orchestrator)

    await engine.execute(orchestration_run_id=workflow_id, value=value, recorder=recorder)
    await engine.execute(orchestration_run_id=workflow_id, value=value, recorder=recorder)

    assert recorder.current.pending_followup is not None
    assert recorder.current.pending_followup.state == "WAITING_TEAM_REQUIREMENTS"
    assert recorder.blocks[0][1] == recorder.blocks[1][1]
    assert recorder.blocks[0][1].endswith(f"{workflow_id}:requirements_wait")

    waiting = recorder.current.pending_followup
    assert waiting is not None
    recorder.current = recorder.current.model_copy(
        update={"pending_followup": waiting.mark_ready()}
    )
    orchestrator.final = True
    await engine.execute(orchestration_run_id=workflow_id, value=value, recorder=recorder)

    assert recorder.current.pending_followup is not None
    assert recorder.current.pending_followup.state == "COMPLETED"
    assert recorder.blocks[2][1].endswith(f"{workflow_id}:team_result")
    assert recorder.blocks[2][1] != recorder.blocks[1][1]
