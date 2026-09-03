"""Pure, deterministic candidate filtering, scoring, and team allocation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.modules.people_capacity.domain.skills import VerifiedPersonSkill
from app.modules.people_capacity.domain.workload import WeeklyWorkload
from app.modules.work.planning.assignment.domain.requirements import (
    TeamRequirement,
    canonical_skill_label,
)

_SCORE_QUANTUM = Decimal("0.0001")
_ZERO = Decimal("0").quantize(_SCORE_QUANTUM)
_ONE = Decimal("1")
_RANKING_V1_WEIGHTS = (
    Decimal("0.50"),
    Decimal("0.30"),
    Decimal("0.15"),
    Decimal("0.05"),
)


class InvalidRankingInputError(ValueError):
    """A ranking-only projection is malformed or outside its bounded policy range."""


def _score(value: Decimal) -> Decimal:
    return value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def _bounded_ratio(value: Decimal, *, field: str) -> Decimal:
    if not _ZERO <= value <= _ONE:
        raise InvalidRankingInputError(field)
    return value


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    version: str = "ranking-v1"
    skill_weight: Decimal = Decimal("0.50")
    capacity_weight: Decimal = Decimal("0.30")
    evidence_weight: Decimal = Decimal("0.15")
    familiarity_weight: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        weights = (
            self.skill_weight,
            self.capacity_weight,
            self.evidence_weight,
            self.familiarity_weight,
        )
        if self.version != "ranking-v1" or weights != _RANKING_V1_WEIGHTS:
            raise InvalidRankingInputError("policy")


@dataclass(frozen=True, slots=True)
class CandidateSkill:
    """A verified skill joined to its normalized organization Skill label."""

    skill_label: str
    verified_skill: VerifiedPersonSkill

    def __post_init__(self) -> None:
        normalized = canonical_skill_label(self.skill_label)
        if not normalized:
            raise InvalidRankingInputError("skill_label")
        object.__setattr__(self, "skill_label", normalized)


@dataclass(frozen=True, slots=True)
class Candidate:
    """Narrow, auditable ranking inputs; no protected or model-derived values."""

    membership_id: UUID
    organization_id: UUID
    active: bool
    policy_allowed: bool
    skills: tuple[CandidateSkill, ...]
    workloads: tuple[WeeklyWorkload, ...]
    evidence_ratio: Decimal
    familiarity_ratio: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "skills", tuple(self.skills))
        object.__setattr__(self, "workloads", tuple(self.workloads))
        _bounded_ratio(self.evidence_ratio, field="evidence_ratio")
        _bounded_ratio(self.familiarity_ratio, field="familiarity_ratio")


@dataclass(frozen=True, slots=True)
class CandidateScore:
    membership_id: UUID
    requirement_id: UUID
    eligible: bool
    hard_failure_codes: tuple[str, ...]
    skill_points: Decimal
    capacity_points: Decimal
    evidence_points: Decimal
    familiarity_points: Decimal
    total_points: Decimal
    policy_version: str


@dataclass(frozen=True, slots=True)
class TeamAllocation:
    requirement_id: UUID
    membership_id: UUID
    allocated_effort_hours: Decimal


@dataclass(frozen=True, slots=True)
class UncoveredDemand:
    requirement_id: UUID
    uncovered_effort_hours: Decimal


@dataclass(frozen=True, slots=True)
class RequirementAlternatives:
    requirement_id: UUID
    candidate_membership_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class TeamSelection:
    allocations: tuple[TeamAllocation, ...]
    uncovered: tuple[UncoveredDemand, ...]
    alternatives: tuple[RequirementAlternatives, ...]


def _matching_skill(
    candidate: Candidate, requirement: TeamRequirement
) -> VerifiedPersonSkill | None:
    matching = tuple(
        item.verified_skill
        for item in candidate.skills
        if item.skill_label == requirement.skill_label
        and item.verified_skill.active
        and item.verified_skill.organization_id == candidate.organization_id
        and item.verified_skill.membership_id == candidate.membership_id
    )
    if not matching:
        return None
    return max(matching, key=lambda item: (int(item.level), str(item.id)))


def _matching_workload(candidate: Candidate, requirement: TeamRequirement) -> WeeklyWorkload | None:
    matching = tuple(
        item
        for item in candidate.workloads
        if item.membership_id == candidate.membership_id
        and item.project_week_id == requirement.project_week_id
    )
    if len(matching) != 1:
        return None
    return matching[0]


def _failure_codes(candidate: Candidate, requirement: TeamRequirement) -> tuple[str, ...]:
    failures: list[str] = []
    if not candidate.active:
        failures.append("INACTIVE_MEMBER")
    if candidate.organization_id != requirement.organization_id:
        failures.append("CROSS_TENANT")
    if not candidate.policy_allowed:
        failures.append("POLICY_DENIED")
    skill = _matching_skill(candidate, requirement)
    if skill is None:
        failures.append("SKILL_MISSING")
    elif skill.level < requirement.minimum_level:
        failures.append("SKILL_BELOW_MINIMUM")
    workload = _matching_workload(candidate, requirement)
    if workload is None:
        failures.append("WEEKLY_WORKLOAD_MISSING")
    elif workload.residual_capacity_hours == 0:
        failures.append("NO_RESIDUAL_CAPACITY")
    return tuple(failures)


def _validate_unique_candidate_memberships(candidates: tuple[Candidate, ...]) -> None:
    membership_ids = tuple(candidate.membership_id for candidate in candidates)
    if len(membership_ids) != len(set(membership_ids)):
        raise InvalidRankingInputError("membership_id")


def _validate_unique_requirement_ids(requirements: tuple[TeamRequirement, ...]) -> None:
    requirement_ids = tuple(requirement.id for requirement in requirements)
    if len(requirement_ids) != len(set(requirement_ids)):
        raise InvalidRankingInputError("requirement_id")


def _score_candidate(
    policy: RankingPolicy,
    requirement: TeamRequirement,
    candidate: Candidate,
) -> CandidateScore:
    failures = _failure_codes(candidate, requirement)
    if failures:
        return CandidateScore(
            membership_id=candidate.membership_id,
            requirement_id=requirement.id,
            eligible=False,
            hard_failure_codes=failures,
            skill_points=_ZERO,
            capacity_points=_ZERO,
            evidence_points=_ZERO,
            familiarity_points=_ZERO,
            total_points=_ZERO,
            policy_version=policy.version,
        )
    skill = _matching_skill(candidate, requirement)
    workload = _matching_workload(candidate, requirement)
    assert skill is not None
    assert workload is not None
    skill_points = _score(policy.skill_weight * Decimal(int(skill.level)) / Decimal("5"))
    capacity_ratio = min(
        Decimal(workload.residual_capacity_hours) / requirement.required_effort_hours,
        _ONE,
    )
    capacity_points = _score(policy.capacity_weight * capacity_ratio)
    evidence_points = _score(policy.evidence_weight * candidate.evidence_ratio)
    familiarity_points = _score(policy.familiarity_weight * candidate.familiarity_ratio)
    return CandidateScore(
        membership_id=candidate.membership_id,
        requirement_id=requirement.id,
        eligible=True,
        hard_failure_codes=(),
        skill_points=skill_points,
        capacity_points=capacity_points,
        evidence_points=evidence_points,
        familiarity_points=familiarity_points,
        total_points=_score(skill_points + capacity_points + evidence_points + familiarity_points),
        policy_version=policy.version,
    )


def rank_candidates(
    policy: RankingPolicy,
    requirement: TeamRequirement,
    candidates: Iterable[Candidate],
) -> tuple[CandidateScore, ...]:
    """Return all scored candidates, with eligible rows first in stable score order."""

    candidate_values = tuple(candidates)
    _validate_unique_candidate_memberships(candidate_values)
    scores = tuple(
        _score_candidate(policy, requirement, candidate) for candidate in candidate_values
    )
    return tuple(
        sorted(
            scores,
            key=lambda item: (
                not item.eligible,
                -item.total_points if item.eligible else Decimal("0"),
                str(item.membership_id),
            ),
        )
    )


def select_team(
    policy: RankingPolicy,
    *,
    requirements: Iterable[TeamRequirement],
    candidates: Iterable[Candidate],
) -> TeamSelection:
    """Allocate full requirements greedily without relaxing any hard constraint."""

    requirement_values = tuple(requirements)
    candidate_values = tuple(candidates)
    _validate_unique_requirement_ids(requirement_values)
    _validate_unique_candidate_memberships(candidate_values)
    rankings = {
        requirement.id: rank_candidates(policy, requirement, candidate_values)
        for requirement in requirement_values
    }
    ordered_requirements = tuple(
        sorted(
            requirement_values,
            key=lambda item: (
                sum(score.eligible for score in rankings[item.id]),
                # Task 8 has no chronological Project Week field; UUID is its
                # sole stable deterministic week key until a later contract adds one.
                str(item.project_week_id),
                item.skill_label,
                str(item.id),
            ),
        )
    )
    residual = {
        (candidate.membership_id, workload.project_week_id): Decimal(
            workload.residual_capacity_hours
        )
        for candidate in candidate_values
        for workload in candidate.workloads
        if workload.membership_id == candidate.membership_id
    }
    allocations: list[TeamAllocation] = []
    uncovered: list[UncoveredDemand] = []
    alternatives: list[RequirementAlternatives] = []
    for requirement in ordered_requirements:
        ranked = rankings[requirement.id]
        eligible = tuple(score for score in ranked if score.eligible)
        remaining_effort = requirement.required_effort_hours
        for score in eligible:
            if remaining_effort == 0:
                break
            capacity_key = (score.membership_id, requirement.project_week_id)
            available_effort = residual.get(capacity_key, _ZERO)
            allocated_effort = min(available_effort, remaining_effort)
            if allocated_effort == 0:
                continue
            residual[capacity_key] = available_effort - allocated_effort
            remaining_effort -= allocated_effort
            allocations.append(
                TeamAllocation(
                    requirement.id,
                    score.membership_id,
                    allocated_effort,
                )
            )
        if remaining_effort > 0:
            uncovered.append(UncoveredDemand(requirement.id, remaining_effort))
            alternatives.append(
                RequirementAlternatives(
                    requirement.id,
                    tuple(score.membership_id for score in eligible),
                )
            )
    return TeamSelection(tuple(allocations), tuple(uncovered), tuple(alternatives))
