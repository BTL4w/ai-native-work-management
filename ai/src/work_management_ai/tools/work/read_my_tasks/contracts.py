"""Contracts for deterministic assigned-Task reads."""

from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from work_management_ai.agents.work_intelligence.contracts import EvidenceItem
from work_management_ai.runtime.contracts import ActorReference


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadMyTasksInput(_StrictFrozenModel):
    status: Literal["TO_DO", "IN_PROGRESS", "DONE"] | None
    due_from: date | None
    due_to: date | None
    limit: int = Field(ge=1, le=100)


class TaskReadRecord(_StrictFrozenModel):
    id: UUID
    project_id: UUID
    title: str = Field(min_length=1, max_length=200)
    status: Literal["TO_DO", "IN_PROGRESS", "DONE"]
    due_date: date | None
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class ReadMyTasksOutput(_StrictFrozenModel):
    resolution: Literal["UNIQUE", "NOT_FOUND"]
    evidence: tuple[EvidenceItem, ...]
    next_task_id: UUID | None


class ReadMyTasksApplicationPort(Protocol):
    async def read_my_tasks(
        self,
        *,
        actor: ActorReference,
        status: Literal["TO_DO", "IN_PROGRESS", "DONE"] | None,
        due_from: date | None,
        due_to: date | None,
        limit: int,
    ) -> tuple[TaskReadRecord, ...]: ...
