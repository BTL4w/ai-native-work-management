"""Pure immutable recommendation snapshots and deterministic manual revisions."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.modules.work.planning.assignment.domain.ranking_preview import (
    CandidateRankingPreview,
    RankingPreview,
    RankingUncoveredPreview,
)


class RecommendationError(ValueError):
    def __init__(self, code: str, current_version: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.current_version = current_version


type RecommendationStatus = Literal["PROPOSED", "APPROVED", "REJECTED", "STALE"]


@dataclass(frozen=True, slots=True)
class RequirementDemand:
    requirement_id: UUID
    project_week_id: UUID
    effort_hours: Decimal


@dataclass(frozen=True, slots=True)
class CandidateOverride:
    requirement_id: UUID
    selected_membership_id: UUID
    override_reason: str | None = None
    allocated_effort_hours: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RecommendationSelection:
    requirement_id: UUID
    membership_id: UUID
    allocated_effort_hours: Decimal
    warning_codes: tuple[str, ...] = ()
    override_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecommendationDiff:
    added_membership_ids: tuple[UUID, ...]
    removed_membership_ids: tuple[UUID, ...]
    before: tuple[RecommendationSelection, ...]
    after: tuple[RecommendationSelection, ...]


@dataclass(frozen=True, slots=True)
class RecommendationVersion:
    recommendation_id: UUID
    version: int
    requirement_set_id: UUID
    requirement_version: int
    policy_version: str
    selections: tuple[RecommendationSelection, ...]
    alternatives: tuple[CandidateRankingPreview, ...]
    uncovered: tuple[RankingUncoveredPreview, ...]
    demands: tuple[RequirementDemand, ...]
    diff: RecommendationDiff | None
    status: RecommendationStatus = "PROPOSED"
    explanation_status: Literal["NOT_REQUESTED", "AVAILABLE", "UNAVAILABLE"] = "NOT_REQUESTED"
    replayed: bool = False


def build_version(
    *,
    recommendation_id: UUID,
    preview: RankingPreview,
    demands: tuple[RequirementDemand, ...],
    base: RecommendationVersion | None = None,
    overrides: tuple[CandidateOverride, ...] | None = None,
    enforce_manual_override_reasons: bool = True,
) -> RecommendationVersion:
    if preview.policy_version != "ranking-v1":
        raise RecommendationError("STALE_POLICY")
    if base and (
        base.requirement_set_id != preview.requirement_set_id
        or base.requirement_version != preview.requirement_version
    ):
        raise RecommendationError("STALE_REQUIREMENTS")
    if base and base.status != "PROPOSED":
        raise RecommendationError("RECOMMENDATION_NOT_PROPOSED")
    demands = tuple(sorted(demands, key=lambda item: str(item.requirement_id)))
    candidates_ordered = tuple(
        sorted(
            preview.candidates,
            key=lambda item: (
                str(item.requirement_id),
                not item.eligible,
                -item.total_points,
                str(item.membership_id),
            ),
        )
    )
    demand_by_id = {item.requirement_id: item for item in demands}
    candidates = {(c.requirement_id, c.membership_id): c for c in candidates_ordered}
    choices = (
        overrides
        if overrides is not None
        else tuple(
            CandidateOverride(a.requirement_id, a.membership_id, None, a.allocated_effort_hours)
            for a in sorted(
                preview.allocations,
                key=lambda item: (str(item.requirement_id), str(item.membership_id)),
            )
        )
    )
    selected: list[RecommendationSelection] = []
    used: dict[tuple[UUID, UUID], Decimal] = {}
    covered: dict[UUID, Decimal] = {}
    seen: set[tuple[UUID, UUID]] = set()
    for choice in choices:
        key = (choice.requirement_id, choice.selected_membership_id)
        demand = demand_by_id.get(choice.requirement_id)
        candidate = candidates.get(key)
        if demand is None or key in seen:
            raise RecommendationError("INVALID_SELECTION")
        seen.add(key)
        if candidate is None or not candidate.eligible or candidate.hard_failure_codes:
            raise RecommendationError("CANDIDATE_INELIGIBLE")
        effort = (
            choice.allocated_effort_hours
            if choice.allocated_effort_hours is not None
            else demand.effort_hours
        )
        if not effort.is_finite() or effort <= 0:
            raise RecommendationError("INVALID_ALLOCATION")
        covered[demand.requirement_id] = covered.get(demand.requirement_id, Decimal(0)) + effort
        if covered[demand.requirement_id] > demand.effort_hours:
            raise RecommendationError("DEMAND_EXCEEDED")
        capacity_key = (candidate.membership_id, demand.project_week_id)
        used[capacity_key] = used.get(capacity_key, Decimal(0)) + effort
        warnings: list[str] = []
        if candidate.residual_capacity_hours is None:
            warnings.append("CAPACITY_UNKNOWN")
        elif used[capacity_key] > candidate.residual_capacity_hours:
            warnings.append("CAPACITY_EXCEEDED")
        top = next(
            (
                c
                for c in candidates_ordered
                if c.requirement_id == demand.requirement_id and c.eligible
            ),
            None,
        )
        if (
            enforce_manual_override_reasons
            and overrides is not None
            and top
            and top.membership_id != candidate.membership_id
        ):
            warnings.append("LOWER_RANKED_CANDIDATE")
        reason = choice.override_reason.strip() if choice.override_reason else None
        if reason and len(reason) > 500:
            raise RecommendationError("INVALID_OVERRIDE_REASON")
        if warnings and not reason:
            raise RecommendationError("OVERRIDE_REASON_REQUIRED")
        selected.append(
            RecommendationSelection(
                demand.requirement_id, candidate.membership_id, effort, tuple(warnings), reason
            )
        )
    selections = tuple(
        sorted(selected, key=lambda item: (str(item.requirement_id), str(item.membership_id)))
    )
    uncovered = tuple(
        RankingUncoveredPreview(
            d.requirement_id, d.effort_hours - covered.get(d.requirement_id, Decimal(0))
        )
        for d in demands
        if covered.get(d.requirement_id, Decimal(0)) < d.effort_hours
    )
    diff = None
    if base:
        before = {s.membership_id for s in base.selections}
        after = {s.membership_id for s in selections}
        diff = RecommendationDiff(
            tuple(sorted(after - before, key=str)),
            tuple(sorted(before - after, key=str)),
            base.selections,
            selections,
        )
    return RecommendationVersion(
        recommendation_id,
        base.version + 1 if base else 1,
        preview.requirement_set_id,
        preview.requirement_version,
        preview.policy_version,
        selections,
        candidates_ordered,
        uncovered,
        demands,
        diff,
    )
