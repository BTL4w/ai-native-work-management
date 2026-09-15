"""Approved Project Team membership is independent of Task assignment."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProjectTeamMembership:
    id: UUID
    project_id: UUID
    membership_id: UUID
    decision_id: UUID
    active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RecommendationFeedback:
    id: UUID
    recommendation_id: UUID
    version: int
    kind: str
    comment: str
    replayed: bool = False
