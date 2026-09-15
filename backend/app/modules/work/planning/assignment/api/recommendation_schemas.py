"""Typed public lifecycle requests and immutable response projections."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.work.planning.assignment.application.ranking_preview import (
    CandidateRankingPreview,
    RankingUncoveredPreview,
)
from app.modules.work.planning.assignment.domain.recommendations import (
    RecommendationDiff,
    RecommendationSelection,
    RequirementDemand,
)


class CreateRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_set_id: UUID
    requirement_version: int = Field(gt=0)
    policy_version: str = Field(default="ranking-v1", min_length=1, max_length=64)


class CandidateOverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: UUID
    selected_membership_id: UUID
    override_reason: str | None = Field(default=None, max_length=500)
    allocated_effort_hours: Decimal | None = Field(
        default=None, gt=0, max_digits=20, decimal_places=4
    )


class ReviseRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overrides: tuple[CandidateOverrideInput, ...] = Field(max_length=1000)


class DecideRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


class RecommendationFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(gt=0)
    kind: Literal["accept", "override", "reject"]
    comment: str = Field(default="", max_length=2000)


class RecommendationVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    recommendation_id: UUID
    version: int
    requirement_set_id: UUID
    requirement_version: int
    policy_version: str
    status: Literal["PROPOSED", "APPROVED", "REJECTED", "STALE"]
    selections: tuple[RecommendationSelection, ...]
    alternatives: tuple[CandidateRankingPreview, ...]
    uncovered: tuple[RankingUncoveredPreview, ...]
    demands: tuple[RequirementDemand, ...]
    diff: RecommendationDiff | None
    explanation_status: Literal["NOT_REQUESTED", "AVAILABLE", "UNAVAILABLE"]


class RecommendationFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    recommendation_id: UUID
    version: int
    kind: Literal["accept", "override", "reject"]
    comment: str


class ProjectTeamMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    membership_id: UUID
    decision_id: UUID
    active: bool
    created_at: datetime


class ProjectTeamResponse(BaseModel):
    memberships: tuple[ProjectTeamMembershipResponse, ...]
