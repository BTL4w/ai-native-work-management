"""Contracts for tenant-scoped deterministic workload reads."""

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from work_management_ai.agents.assignment.contracts import ProjectWorkloadSnapshot
from work_management_ai.runtime.contracts import ActorReference


class ReadWorkloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID


ReadWorkloadOutput = ProjectWorkloadSnapshot


class ReadWorkloadApplicationPort(Protocol):
    async def read_workload(
        self, *, actor: ActorReference, value: ReadWorkloadInput
    ) -> ReadWorkloadOutput: ...


__all__ = ["ReadWorkloadApplicationPort", "ReadWorkloadInput", "ReadWorkloadOutput"]
