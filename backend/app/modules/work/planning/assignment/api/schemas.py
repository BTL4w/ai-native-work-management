"""Public Team Requirement request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.work.planning.assignment.application.requirement_service import RequirementSet


class RequirementItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: UUID
    minimum_level: int = Field(ge=1, le=5)
    project_week_id: UUID
    effort_hours: int = Field(gt=0, le=2147483647, strict=True)
    source_task_ids: tuple[UUID, ...]


class IncompleteRequirementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    reason: str


class RequirementItemResponse(RequirementItemInput):
    id: UUID


class TeamRequirementSetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    organization_id: UUID
    project_id: UUID
    version: int
    status: Literal["DRAFT", "CONFIRMED", "STALE"]
    items: tuple[RequirementItemResponse, ...]
    incomplete_items: tuple[IncompleteRequirementResponse, ...]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, value: RequirementSet) -> "TeamRequirementSetResponse":
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            project_id=value.project_id,
            version=value.version,
            status=value.status.value,
            items=tuple(
                RequirementItemResponse(
                    id=item.id,
                    skill_id=item.skill_id,
                    minimum_level=int(item.minimum_level),
                    project_week_id=item.project_week_id,
                    effort_hours=item.effort_hours,
                    source_task_ids=item.source_task_ids,
                )
                for item in value.items
            ),
            incomplete_items=tuple(
                IncompleteRequirementResponse(task_id=item.task_id, reason=item.reason)
                for item in value.incomplete_items
            ),
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class ReviseTeamRequirementsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["revise"]
    items: tuple[RequirementItemInput, ...]
    incomplete_items: tuple[IncompleteRequirementResponse, ...] = ()


class ConfirmTeamRequirementsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["confirm"]


TeamRequirementsPatchRequest = ReviseTeamRequirementsRequest | ConfirmTeamRequirementsRequest
