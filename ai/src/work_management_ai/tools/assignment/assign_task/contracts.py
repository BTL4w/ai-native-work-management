"""Contracts for one explicit exact Manager Task assignment."""

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from work_management_ai.agents.assignment.contracts import ExplicitAssignmentSnapshot
from work_management_ai.runtime.contracts import ActorReference


class AssignTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    task_version: int = Field(ge=1)
    membership_id: UUID


AssignTaskOutput = ExplicitAssignmentSnapshot


class AssignTaskApplicationPort(Protocol):
    async def assign_task(
        self,
        *,
        actor: ActorReference,
        value: AssignTaskInput,
        idempotency_key: str,
    ) -> AssignTaskOutput: ...


__all__ = ["AssignTaskApplicationPort", "AssignTaskInput", "AssignTaskOutput"]
