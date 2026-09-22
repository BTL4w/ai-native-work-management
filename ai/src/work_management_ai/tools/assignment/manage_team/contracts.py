"""Contracts for creating or revising a deterministic Project Team proposal."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from work_management_ai.agents.assignment.contracts import (
    TeamRecommendationSnapshot,
    TeamRequirementsPendingSnapshot,
)
from work_management_ai.runtime.contracts import ActorReference


class ManageTeamInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["CREATE", "REVISE"]
    project_id: UUID | None = None
    planning_proposal_id: UUID | None = None
    planning_proposal_version: int | None = Field(default=None, ge=1)
    recommendation_id: UUID | None = None
    recommendation_version: int | None = Field(default=None, ge=1)
    revision_instruction: str | None = Field(default=None, min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def exact_references_are_present(self) -> "ManageTeamInput":
        if (self.planning_proposal_id is None) != (self.planning_proposal_version is None):
            raise ValueError("planning proposal provenance must be complete")
        if self.action == "CREATE" and self.project_id is None:
            raise ValueError("project_id is required to create a recommendation")
        if self.action == "REVISE" and (
            self.project_id is None
            or self.recommendation_id is None
            or self.recommendation_version is None
            or self.revision_instruction is None
        ):
            raise ValueError("exact recommendation version and instruction are required")
        return self


ManageTeamOutput = TeamRecommendationSnapshot | TeamRequirementsPendingSnapshot


class ManageTeamApplicationPort(Protocol):
    async def manage_team(
        self,
        *,
        actor: ActorReference,
        value: ManageTeamInput,
        idempotency_key: str,
    ) -> ManageTeamOutput: ...


__all__ = ["ManageTeamApplicationPort", "ManageTeamInput", "ManageTeamOutput"]
