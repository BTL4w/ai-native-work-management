"""Typed contracts for the Phase 2 Orchestrator Agent."""

from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from work_management_ai.runtime.contracts import (
    ActorReference,
    AgentHandoff,
    AgentId,
    AgentResult,
    JsonValue,
    ResolvedActorContext,
    ResponseBlock,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StepMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    PROPOSAL = "PROPOSAL"


class ExecutionStep(_StrictFrozenModel):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    target_agent_id: AgentId
    target_agent_version: str = Field(min_length=1, max_length=64)
    capability: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=4_000)
    typed_input: dict[str, JsonValue]
    depends_on: tuple[str, ...] = Field(default=(), max_length=8)
    mode: StepMode


class ExecutionPlan(_StrictFrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    objectives: tuple[str, ...] = Field(min_length=1, max_length=8)
    steps: tuple[ExecutionStep, ...] = Field(default=(), max_length=8)
    unavailable_capabilities: tuple[str, ...] = Field(default=(), max_length=8)
    response_language: Literal["vi", "en"]

    @model_validator(mode="after")
    def require_an_executable_or_unavailable_outcome(self) -> "ExecutionPlan":
        if not self.steps and not self.unavailable_capabilities:
            raise ValueError("execution plan must contain a step or unavailable capability")
        return self


class ConversationExcerpt(_StrictFrozenModel):
    role: Literal["USER", "ASSISTANT"]
    text: str = Field(min_length=1, max_length=8_000)


class ActivePlanningContext(_StrictFrozenModel):
    workflow_run_id: UUID
    workflow_status: str = Field(min_length=1, max_length=100)
    proposal_id: UUID | None
    proposal_version: int | None = Field(default=None, ge=1)
    proposal_status: str | None = Field(default=None, min_length=1, max_length=100)
    requested_operation: Literal["RESUME_INPUT", "REVISE"]


class ActiveConversationContext(_StrictFrozenModel):
    recent_messages: tuple[ConversationExcerpt, ...] = Field(max_length=12)
    active_planning: ActivePlanningContext | None = None


class OrchestratorInput(_StrictFrozenModel):
    orchestration_run_id: UUID | None = None
    conversation_id: UUID
    turn_id: UUID
    message: str = Field(min_length=1, max_length=8_000)
    locale: Literal["vi", "en"]
    actor: ActorReference
    active_context: ActiveConversationContext


class OrchestratorSynthesis(_StrictFrozenModel):
    blocks: tuple[ResponseBlock, ...] = Field(min_length=1, max_length=16)


class OrchestratorStatus(StrEnum):
    COMPLETED = "COMPLETED"
    AWAITING_INPUT = "AWAITING_INPUT"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    FAILED = "FAILED"


class OrchestratorOutput(_StrictFrozenModel):
    execution_plan: ExecutionPlan | None
    agent_results: tuple[AgentResult, ...]
    blocks: tuple[ResponseBlock, ...]
    completed_step_ids: tuple[str, ...]
    status: OrchestratorStatus
    stop_reason: str = Field(min_length=1, max_length=100)
    replans_used: int = Field(ge=0, le=2)
    model_refs: tuple[str, ...]


class ActorContextResolverPort(Protocol):
    async def resolve(self, reference: ActorReference) -> ResolvedActorContext: ...


class SpecialistRunnerPort(Protocol):
    async def run_specialist(self, handoff: AgentHandoff) -> AgentResult: ...
