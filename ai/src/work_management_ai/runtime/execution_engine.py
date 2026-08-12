"""Durable orchestration wrapper around the bounded Orchestrator harness."""

from collections.abc import Mapping
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from work_management_ai.agents.orchestrator.contracts import (
    ExecutionPlan,
    OrchestratorInput,
    OrchestratorOutput,
)
from work_management_ai.runtime.contracts import (
    AgentBudget,
    AgentHandoff,
    AgentHarness,
    AgentId,
    AgentResult,
    AgentRunStatus,
    ResponseBlock,
)


class ExecutionCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    orchestration_run_id: UUID
    sequence: int = Field(ge=1)
    node: str
    plan: ExecutionPlan
    completed_step_ids: tuple[str, ...]
    agent_result_ids: tuple[UUID, ...]
    remaining_budget: AgentBudget


class RecordedAgentRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    status: AgentRunStatus
    replayed_result: AgentResult | None = None


class ExecutionRecorderPort(Protocol):
    async def load_checkpoint(self, orchestration_run_id: UUID) -> ExecutionCheckpoint | None: ...
    async def start_agent_run(self, handoff: AgentHandoff) -> RecordedAgentRun: ...
    async def finish_agent_run(self, run_id: UUID, result: AgentResult) -> None: ...
    async def save_checkpoint(self, checkpoint: ExecutionCheckpoint) -> None: ...
    async def append_public_blocks(
        self,
        conversation_id: UUID,
        turn_id: UUID,
        blocks: tuple[ResponseBlock, ...],
        dedupe_key: str,
    ) -> None: ...


class _OrchestratorPort(Protocol):
    async def run_turn(self, value: OrchestratorInput) -> OrchestratorOutput: ...


class DurableSpecialistRunner:
    """Replay completed step identities and persist new Specialist results."""

    def __init__(
        self,
        *,
        recorder: ExecutionRecorderPort,
        harnesses: Mapping[AgentId, AgentHarness],
    ) -> None:
        self._recorder = recorder
        self._harnesses = harnesses

    async def run_specialist(self, handoff: AgentHandoff) -> AgentResult:
        recorded = await self._recorder.start_agent_run(handoff)
        if recorded.status is AgentRunStatus.COMPLETED:
            if recorded.replayed_result is None:
                raise RuntimeError("AGENT_REPLAY_RESULT_MISSING")
            return recorded.replayed_result
        harness = self._harnesses.get(handoff.target_agent_id)
        if harness is None:
            raise RuntimeError("AGENT_HARNESS_NOT_REGISTERED")
        result = await harness.run(handoff)
        await self._recorder.finish_agent_run(recorded.id, result)
        return result


class AgentExecutionEngine:
    def __init__(self, orchestrator: _OrchestratorPort) -> None:
        self._orchestrator = orchestrator

    async def execute(
        self,
        *,
        orchestration_run_id: UUID,
        value: OrchestratorInput,
        recorder: ExecutionRecorderPort,
    ) -> OrchestratorOutput:
        """Run outside caller transactions and persist a recoverable terminal checkpoint.

        Completed steps are represented by persisted Agent Runs in the recorder;
        adapters replay their typed result before a Harness is invoked again.
        """
        checkpoint = await recorder.load_checkpoint(orchestration_run_id)
        output = await self._orchestrator.run_turn(value)
        if output.execution_plan is not None:
            budget = AgentBudget(
                max_iterations=8,
                max_tool_calls=0,
                max_handoffs=6,
                max_replans=2,
                timeout_seconds=120,
            )
            await recorder.save_checkpoint(
                ExecutionCheckpoint(
                    orchestration_run_id=orchestration_run_id,
                    sequence=(checkpoint.sequence + 1) if checkpoint else 1,
                    node="terminal",
                    plan=output.execution_plan,
                    completed_step_ids=output.completed_step_ids,
                    agent_result_ids=tuple(
                        uuid5(
                            NAMESPACE_URL,
                            f"agent-run:{value.turn_id}:{step_id}",
                        )
                        for step_id in output.completed_step_ids
                    ),
                    remaining_budget=budget,
                )
            )
        await recorder.append_public_blocks(
            value.conversation_id,
            value.turn_id,
            output.blocks,
            f"assistant:{value.turn_id}:terminal",
        )
        return output
