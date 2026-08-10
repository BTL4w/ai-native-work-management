"""Contracts for proposal-only Planning run operations."""

from typing import Protocol

from work_management_ai.agents.planning.contracts import (
    PlanningAgentInput,
    PlanningAgentOutput,
)
from work_management_ai.runtime.contracts import ActorReference

PlanningRunToolInput = PlanningAgentInput
PlanningRunToolOutput = PlanningAgentOutput


class PlanningRunApplicationPort(Protocol):
    async def manage_run(
        self,
        *,
        actor: ActorReference,
        value: PlanningRunToolInput,
        idempotency_key: str,
    ) -> PlanningRunToolOutput: ...


__all__ = ["PlanningRunApplicationPort", "PlanningRunToolInput", "PlanningRunToolOutput"]
