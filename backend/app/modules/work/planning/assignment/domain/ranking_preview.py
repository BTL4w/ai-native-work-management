"""Immutable public projections of deterministic candidate ranking."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RankingEvidence:
    id: UUID
    summary: str
    source_resource_type: str
    source_resource_id: UUID


@dataclass(frozen=True, slots=True)
class CandidateRankingPreview:
    requirement_id: UUID
    membership_id: UUID
    display_name: str
    eligible: bool
    hard_failure_codes: tuple[str, ...]
    skill_points: Decimal
    capacity_points: Decimal
    evidence_points: Decimal
    familiarity_points: Decimal
    total_points: Decimal
    effective_capacity_hours: int | None
    residual_capacity_hours: int | None
    evidence: tuple[RankingEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "hard_failure_codes", tuple(self.hard_failure_codes))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class RankingAllocationPreview:
    requirement_id: UUID
    membership_id: UUID
    allocated_effort_hours: Decimal


@dataclass(frozen=True, slots=True)
class RankingUncoveredPreview:
    requirement_id: UUID
    uncovered_effort_hours: Decimal


@dataclass(frozen=True, slots=True)
class RankingPreview:
    requirement_set_id: UUID
    requirement_version: int
    policy_version: str
    origin: Literal["DETERMINISTIC"]
    candidates: tuple[CandidateRankingPreview, ...]
    allocations: tuple[RankingAllocationPreview, ...]
    uncovered: tuple[RankingUncoveredPreview, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "allocations", tuple(self.allocations))
        object.__setattr__(self, "uncovered", tuple(self.uncovered))
