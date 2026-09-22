"""Typed contracts for deterministic Assignment operations and explanations."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from work_management_ai.runtime.contracts import JsonValue


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssignmentOperation(StrEnum):
    RECOMMEND_TEAM = "RECOMMEND_TEAM"
    REVISE_TEAM = "REVISE_TEAM"
    ANALYZE_WORKLOAD = "ANALYZE_WORKLOAD"
    ASSIGN_TASK_EXPLICITLY = "ASSIGN_TASK_EXPLICITLY"


class AssignmentAgentInput(_StrictFrozenModel):
    operation: AssignmentOperation
    locale: Literal["vi", "en"]
    project_id: UUID | None = None
    planning_proposal_id: UUID | None = None
    planning_proposal_version: int | None = Field(default=None, ge=1)
    recommendation_id: UUID | None = None
    recommendation_version: int | None = Field(default=None, ge=1)
    task_id: UUID | None = None
    task_version: int | None = Field(default=None, ge=1)
    membership_id: UUID | None = None
    revision_instruction: str | None = Field(default=None, min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def references_match_operation(self) -> "AssignmentAgentInput":
        if (self.planning_proposal_id is None) != (self.planning_proposal_version is None):
            raise ValueError("planning proposal provenance must be complete")
        if self.operation in {
            AssignmentOperation.RECOMMEND_TEAM,
            AssignmentOperation.ANALYZE_WORKLOAD,
        }:
            if self.project_id is None:
                raise ValueError("project_id is required")
        elif self.operation is AssignmentOperation.REVISE_TEAM:
            if (
                self.project_id is None
                or self.recommendation_id is None
                or self.recommendation_version is None
                or self.revision_instruction is None
            ):
                raise ValueError("exact recommendation version and instruction are required")
        elif self.operation is AssignmentOperation.ASSIGN_TASK_EXPLICITLY and (
            self.task_id is None or self.task_version is None or self.membership_id is None
        ):
            raise ValueError("exact task, version and membership are required")
        return self


class ScoreBreakdown(_StrictFrozenModel):
    skill_points: Decimal
    capacity_points: Decimal
    evidence_points: Decimal
    familiarity_points: Decimal
    total_points: Decimal


class EvidenceSnapshot(_StrictFrozenModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=2_000)
    source_resource_type: str = Field(min_length=1, max_length=100)
    source_resource_id: UUID
    source_resource_version: int | None = Field(default=None, ge=1)


class SelectedMemberSnapshot(_StrictFrozenModel):
    membership_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    requirement_ids: tuple[UUID, ...] = Field(min_length=1)
    scores: ScoreBreakdown
    evidence: tuple[EvidenceSnapshot, ...] = ()
    workload_ratio: Decimal | None = Field(default=None, ge=0)
    warning_codes: tuple[str, ...] = ()


class CandidateSnapshot(_StrictFrozenModel):
    membership_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    requirement_id: UUID
    eligible: bool
    hard_failure_codes: tuple[str, ...] = ()
    scores: ScoreBreakdown
    evidence: tuple[EvidenceSnapshot, ...] = ()
    workload_ratio: Decimal | None = Field(default=None, ge=0)


class TeamRecommendationSnapshot(_StrictFrozenModel):
    organization_id: UUID
    project_id: UUID
    requirement_set_id: UUID
    requirement_version: int = Field(ge=1)
    recommendation_id: UUID
    version: int = Field(ge=1)
    status: Literal["PROPOSED", "APPROVED", "REJECTED", "STALE"]
    policy_version: str = Field(min_length=1, max_length=64)
    selected_members: tuple[SelectedMemberSnapshot, ...]
    alternatives: tuple[CandidateSnapshot, ...]
    uncovered_requirement_ids: tuple[UUID, ...]
    observed_at: datetime


class TeamRequirementsPendingSnapshot(_StrictFrozenModel):
    kind: Literal["team_requirements_pending"] = "team_requirements_pending"
    organization_id: UUID
    project_id: UUID
    requirement_set_id: UUID
    requirement_version: int = Field(ge=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    observed_at: datetime


class WorkloadSnapshot(_StrictFrozenModel):
    membership_id: UUID
    project_week_id: UUID
    effective_capacity_hours: int = Field(ge=0)
    allocated_effort_hours: int = Field(ge=0)
    residual_capacity_hours: int = Field(ge=0)
    workload_ratio: Decimal | None = Field(default=None, ge=0)


class ProjectWorkloadSnapshot(_StrictFrozenModel):
    organization_id: UUID
    project_id: UUID
    workloads: tuple[WorkloadSnapshot, ...]
    observed_at: datetime


class ExplicitAssignmentSnapshot(_StrictFrozenModel):
    organization_id: UUID
    project_id: UUID
    task_id: UUID
    task_version: int = Field(ge=1)
    membership_id: UUID
    warning_codes: tuple[str, ...] = ()
    effective_capacity_hours: int = Field(ge=0)
    workload_before_hours: int = Field(ge=0)
    workload_after_hours: int = Field(ge=0)
    observed_at: datetime


class GroundedClaim(_StrictFrozenModel):
    text: str = Field(min_length=1, max_length=2_000)
    evidence_ids: tuple[str, ...] = ()


class MemberReason(_StrictFrozenModel):
    membership_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    requirement_ids: tuple[UUID, ...] = Field(min_length=1)
    total_points: Decimal
    workload_ratio: Decimal | None = Field(default=None, ge=0)
    evidence_ids: tuple[str, ...] = ()
    text: str = Field(min_length=1, max_length=2_000)


class GroundedAlternative(_StrictFrozenModel):
    membership_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    requirement_id: UUID
    total_points: Decimal
    evidence_ids: tuple[str, ...] = ()
    text: str = Field(min_length=1, max_length=2_000)


class AssignmentExplanation(_StrictFrozenModel):
    recommendation_id: UUID
    version: int = Field(ge=1)
    member_reasons: tuple[MemberReason, ...]
    risks: tuple[GroundedClaim, ...]
    alternatives: tuple[GroundedAlternative, ...]
    uncovered_requirement_ids: tuple[UUID, ...]


class MemberWorkloadReason(_StrictFrozenModel):
    membership_id: UUID
    project_week_id: UUID
    workload_ratio: Decimal | None = Field(default=None, ge=0)
    text: str = Field(min_length=1, max_length=2_000)


class WorkloadExplanation(_StrictFrozenModel):
    project_id: UUID
    member_reasons: tuple[MemberWorkloadReason, ...]


class AssignmentAgentOutput(_StrictFrozenModel):
    operation: AssignmentOperation
    deterministic_result: dict[str, JsonValue]
    explanation_status: Literal["NOT_REQUESTED", "AVAILABLE", "UNAVAILABLE"]
    explanation: AssignmentExplanation | WorkloadExplanation | None = None

    @model_validator(mode="after")
    def explanation_matches_status(self) -> "AssignmentAgentOutput":
        if (self.explanation_status == "AVAILABLE") != (self.explanation is not None):
            raise ValueError("available explanation status must match explanation content")
        return self


__all__ = [
    "AssignmentAgentInput",
    "AssignmentAgentOutput",
    "AssignmentExplanation",
    "AssignmentOperation",
    "CandidateSnapshot",
    "EvidenceSnapshot",
    "ExplicitAssignmentSnapshot",
    "GroundedAlternative",
    "GroundedClaim",
    "MemberReason",
    "MemberWorkloadReason",
    "ProjectWorkloadSnapshot",
    "ScoreBreakdown",
    "SelectedMemberSnapshot",
    "TeamRecommendationSnapshot",
    "WorkloadExplanation",
    "WorkloadSnapshot",
]
