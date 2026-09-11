"""Public Team Requirement request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.work.planning.assignment.application.ranking_preview import RankingPreview
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


class RefreshTeamRequirementsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["refresh"]


TeamRequirementsPatchRequest = (
    ReviseTeamRequirementsRequest | ConfirmTeamRequirementsRequest | RefreshTeamRequirementsRequest
)


class RankingEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    summary: str
    source_resource_type: str
    source_resource_id: UUID


class CandidateRankingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: UUID
    membership_id: UUID
    display_name: str
    eligible: bool
    hard_failure_codes: tuple[str, ...]
    skill_points: str
    capacity_points: str
    evidence_points: str
    familiarity_points: str
    total_points: str
    effective_capacity_hours: int | None
    residual_capacity_hours: int | None
    evidence: tuple[RankingEvidenceResponse, ...]


class RankingAllocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: UUID
    membership_id: UUID
    allocated_effort_hours: str


class RankingUncoveredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: UUID
    uncovered_effort_hours: str


class RankingPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_set_id: UUID
    requirement_version: int
    policy_version: Literal["ranking-v1"]
    origin: Literal["DETERMINISTIC"]
    candidates: tuple[CandidateRankingResponse, ...]
    allocations: tuple[RankingAllocationResponse, ...]
    uncovered: tuple[RankingUncoveredResponse, ...]

    @classmethod
    def from_domain(cls, value: RankingPreview) -> "RankingPreviewResponse":
        return cls(
            requirement_set_id=value.requirement_set_id,
            requirement_version=value.requirement_version,
            policy_version="ranking-v1",
            origin="DETERMINISTIC",
            candidates=tuple(
                CandidateRankingResponse(
                    requirement_id=item.requirement_id,
                    membership_id=item.membership_id,
                    display_name=item.display_name,
                    eligible=item.eligible,
                    hard_failure_codes=item.hard_failure_codes,
                    skill_points=str(item.skill_points),
                    capacity_points=str(item.capacity_points),
                    evidence_points=str(item.evidence_points),
                    familiarity_points=str(item.familiarity_points),
                    total_points=str(item.total_points),
                    effective_capacity_hours=item.effective_capacity_hours,
                    residual_capacity_hours=item.residual_capacity_hours,
                    evidence=tuple(
                        RankingEvidenceResponse(
                            id=evidence.id,
                            summary=evidence.summary,
                            source_resource_type=evidence.source_resource_type,
                            source_resource_id=evidence.source_resource_id,
                        )
                        for evidence in item.evidence
                    ),
                )
                for item in value.candidates
            ),
            allocations=tuple(
                RankingAllocationResponse(
                    requirement_id=item.requirement_id,
                    membership_id=item.membership_id,
                    allocated_effort_hours=str(item.allocated_effort_hours),
                )
                for item in value.allocations
            ),
            uncovered=tuple(
                RankingUncoveredResponse(
                    requirement_id=item.requirement_id,
                    uncovered_effort_hours=str(item.uncovered_effort_hours),
                )
                for item in value.uncovered
            ),
        )
