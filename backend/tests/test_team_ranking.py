"""Tests for deterministic hard filtering, ranking, and team allocation."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.modules.people_capacity.domain.skills import SkillLevel, VerifiedPersonSkill
from app.modules.people_capacity.domain.workload import WeeklyWorkload
from app.modules.work.planning.assignment.domain.ranking import (
    Candidate,
    CandidateSkill,
    InvalidRankingInputError,
    RankingPolicy,
    TeamRequirement,
    rank_candidates,
    select_team,
)

ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000099")
WEEK_ID = UUID("00000000-0000-0000-0000-000000000002")
REQ_ID = UUID("00000000-0000-0000-0000-000000000003")
ANALYSIS_SKILL_ID = UUID("00000000-0000-0000-0000-000000000004")
WRITING_SKILL_ID = UUID("00000000-0000-0000-0000-000000000005")
MEMBER_A = UUID("00000000-0000-0000-0000-000000000010")
MEMBER_B = UUID("00000000-0000-0000-0000-000000000011")
MEMBER_C = UUID("00000000-0000-0000-0000-000000000012")
NOW = datetime(2026, 9, 4, tzinfo=UTC)
POLICY_V1 = RankingPolicy()
REQ = TeamRequirement(
    id=REQ_ID,
    organization_id=ORGANIZATION_ID,
    project_week_id=WEEK_ID,
    skill_label="analysis",
    minimum_level=SkillLevel.LEVEL_3,
    required_effort_hours=Decimal("8"),
)


def candidate(
    membership_id: UUID,
    *,
    level: SkillLevel = SkillLevel.LEVEL_5,
    residual: int = 16,
    organization_id: UUID = ORGANIZATION_ID,
    active: bool = True,
    policy_allowed: bool = True,
    evidence_ratio: Decimal = Decimal("1"),
    familiarity_ratio: Decimal = Decimal("1"),
    skill_label: str = "analysis",
) -> Candidate:
    skill = VerifiedPersonSkill(
        id=UUID(int=membership_id.int + 1_000),
        organization_id=organization_id,
        membership_id=membership_id,
        skill_id=ANALYSIS_SKILL_ID if skill_label == "analysis" else WRITING_SKILL_ID,
        level=level,
        verified_by_membership_id=MEMBER_C,
        verified_at=NOW,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    workload = WeeklyWorkload(
        membership_id=membership_id,
        project_week_id=WEEK_ID,
        effective_capacity_hours=residual,
        allocated_effort_hours=0,
        residual_capacity_hours=residual,
        workload_ratio=Decimal("0"),
    )
    return Candidate(
        membership_id=membership_id,
        organization_id=organization_id,
        active=active,
        policy_allowed=policy_allowed,
        skills=(CandidateSkill(skill_label=skill_label, verified_skill=skill),),
        workloads=(workload,),
        evidence_ratio=evidence_ratio,
        familiarity_ratio=familiarity_ratio,
    )


CANDIDATES = (candidate(MEMBER_A), candidate(MEMBER_B, evidence_ratio=Decimal("0.5")))


def score_for(membership_id: UUID) -> Decimal:
    return next(
        row.total_points
        for row in rank_candidates(POLICY_V1, REQ, CANDIDATES)
        if row.membership_id == membership_id
    )


def test_same_inputs_produce_same_stable_ranking() -> None:
    first = rank_candidates(policy=POLICY_V1, requirement=REQ, candidates=CANDIDATES)
    second = rank_candidates(policy=POLICY_V1, requirement=REQ, candidates=reversed(CANDIDATES))

    assert first == second
    assert [row.membership_id for row in first] == sorted(
        (row.membership_id for row in first),
        key=lambda value: (-score_for(value), str(value)),
    )


def test_ranking_v1_rejects_alternate_weights_under_its_same_version() -> None:
    with pytest.raises(ValueError):
        RankingPolicy(
            skill_weight=Decimal("0.55"),
            capacity_weight=Decimal("0.25"),
            evidence_weight=Decimal("0.15"),
            familiarity_weight=Decimal("0.05"),
        )


@pytest.mark.parametrize(
    ("value", "failure"),
    [
        (candidate(MEMBER_A, active=False), "INACTIVE_MEMBER"),
        (candidate(MEMBER_A, organization_id=OTHER_ORGANIZATION_ID), "CROSS_TENANT"),
        (candidate(MEMBER_A, level=SkillLevel.LEVEL_2), "SKILL_BELOW_MINIMUM"),
        (candidate(MEMBER_A, residual=0), "NO_RESIDUAL_CAPACITY"),
        (candidate(MEMBER_A, policy_allowed=False), "POLICY_DENIED"),
    ],
)
def test_hard_constraints_make_candidate_ineligible(value: Candidate, failure: str) -> None:
    result = rank_candidates(POLICY_V1, REQ, (value,))[0]

    assert result.eligible is False
    assert failure in result.hard_failure_codes
    assert result.total_points == Decimal("0.0000")


def test_zero_evidence_is_eligible_but_contributes_no_points() -> None:
    result = rank_candidates(
        POLICY_V1,
        REQ,
        (candidate(MEMBER_A, evidence_ratio=Decimal("0"), familiarity_ratio=Decimal("0")),),
    )[0]

    assert result.eligible is True
    assert result.skill_points == Decimal("0.5000")
    assert result.capacity_points == Decimal("0.3000")
    assert result.evidence_points == Decimal("0.0000")
    assert result.familiarity_points == Decimal("0.0000")
    assert result.total_points == Decimal("0.8000")


def test_weighted_components_are_reproducible_and_quantized() -> None:
    result = rank_candidates(
        POLICY_V1,
        REQ,
        (
            candidate(
                MEMBER_A,
                level=SkillLevel.LEVEL_4,
                residual=8,
                evidence_ratio=Decimal("0.33333"),
                familiarity_ratio=Decimal("0.66667"),
            ),
        ),
    )[0]

    assert result.skill_points == Decimal("0.4000")
    assert result.capacity_points == Decimal("0.3000")
    assert result.evidence_points == Decimal("0.0500")
    assert result.familiarity_points == Decimal("0.0333")
    assert result.total_points == Decimal("0.7833")


def test_positive_partial_capacity_is_eligible_and_has_a_differentiated_score() -> None:
    results = rank_candidates(
        POLICY_V1,
        REQ,
        (candidate(MEMBER_A, residual=3), candidate(MEMBER_B, residual=5)),
    )

    by_member = {item.membership_id: item for item in results}
    assert by_member[MEMBER_A].eligible is True
    assert by_member[MEMBER_A].capacity_points == Decimal("0.1125")
    assert by_member[MEMBER_B].eligible is True
    assert by_member[MEMBER_B].capacity_points == Decimal("0.1875")


def test_greedy_selection_combines_partial_capacities_for_one_requirement() -> None:
    result = select_team(
        POLICY_V1,
        requirements=(REQ,),
        candidates=(candidate(MEMBER_A, residual=3), candidate(MEMBER_B, residual=5)),
    )

    assert [(item.membership_id, item.allocated_effort_hours) for item in result.allocations] == [
        (MEMBER_B, Decimal("5")),
        (MEMBER_A, Decimal("3")),
    ]
    assert result.uncovered == ()


def test_selection_reports_only_the_unallocated_partial_capacity_remainder() -> None:
    result = select_team(
        POLICY_V1,
        requirements=(REQ,),
        candidates=(candidate(MEMBER_A, residual=3),),
    )

    assert result.allocations[0].allocated_effort_hours == Decimal("3")
    assert result.uncovered[0].uncovered_effort_hours == Decimal("5")


def test_candidate_skill_canonical_label_matches_requirement() -> None:
    requirement = TeamRequirement(
        id=REQ_ID,
        organization_id=ORGANIZATION_ID,
        project_week_id=WEEK_ID,
        skill_label="Data Analysis",
        minimum_level=SkillLevel.LEVEL_3,
        required_effort_hours=Decimal("8"),
    )
    value = candidate(MEMBER_A, skill_label=" Data   Analysis ")

    assert rank_candidates(POLICY_V1, requirement, (value,))[0].eligible is True


@pytest.mark.parametrize(
    "values",
    [
        (candidate(MEMBER_A), candidate(MEMBER_A, evidence_ratio=Decimal("0.5"))),
        (candidate(MEMBER_A, evidence_ratio=Decimal("0.5")), candidate(MEMBER_A)),
    ],
)
def test_ranking_rejects_duplicate_candidate_membership_ids_regardless_input_order(
    values: tuple[Candidate, Candidate],
) -> None:
    with pytest.raises(InvalidRankingInputError, match="membership_id"):
        rank_candidates(POLICY_V1, REQ, values)


@pytest.mark.parametrize("reverse", [False, True])
def test_selection_rejects_duplicate_candidate_membership_ids_before_allocation(
    reverse: bool,
) -> None:
    values = (
        candidate(MEMBER_A),
        candidate(MEMBER_A, evidence_ratio=Decimal("0.5")),
    )

    with pytest.raises(InvalidRankingInputError, match="membership_id"):
        select_team(
            POLICY_V1,
            requirements=(REQ,),
            candidates=tuple(reversed(values)) if reverse else values,
        )


@pytest.mark.parametrize("reverse", [False, True])
def test_selection_rejects_duplicate_requirement_ids_regardless_input_order(reverse: bool) -> None:
    duplicate = TeamRequirement(
        id=REQ.id,
        organization_id=ORGANIZATION_ID,
        project_week_id=WEEK_ID,
        skill_label="writing",
        minimum_level=SkillLevel.LEVEL_1,
        required_effort_hours=Decimal("8"),
    )
    requirements = (duplicate, REQ) if reverse else (REQ, duplicate)

    with pytest.raises(InvalidRankingInputError, match="requirement_id"):
        select_team(POLICY_V1, requirements=requirements, candidates=(candidate(MEMBER_A),))


def test_selection_keeps_residual_capacity_separate_per_project_week() -> None:
    other_week = UUID("00000000-0000-0000-0000-000000000030")
    other_requirement = TeamRequirement(
        id=UUID("00000000-0000-0000-0000-000000000031"),
        organization_id=ORGANIZATION_ID,
        project_week_id=other_week,
        skill_label="analysis",
        minimum_level=SkillLevel.LEVEL_3,
        required_effort_hours=Decimal("8"),
    )
    base = candidate(MEMBER_A, residual=8)
    member = Candidate(
        membership_id=base.membership_id,
        organization_id=base.organization_id,
        active=base.active,
        policy_allowed=base.policy_allowed,
        skills=base.skills,
        workloads=(
            *base.workloads,
            WeeklyWorkload(
                membership_id=MEMBER_A,
                project_week_id=other_week,
                effective_capacity_hours=8,
                allocated_effort_hours=0,
                residual_capacity_hours=8,
                workload_ratio=Decimal("0"),
            ),
        ),
        evidence_ratio=base.evidence_ratio,
        familiarity_ratio=base.familiarity_ratio,
    )

    first = select_team(
        POLICY_V1,
        requirements=(REQ, other_requirement),
        candidates=(member, candidate(MEMBER_B, residual=8)),
    )
    second = select_team(
        POLICY_V1,
        requirements=(other_requirement, REQ),
        candidates=(candidate(MEMBER_B, residual=8), member),
    )

    assert first == second
    assert [(item.requirement_id, item.allocated_effort_hours) for item in first.allocations] == [
        (other_requirement.id, Decimal("8")),
        (REQ.id, Decimal("8")),
    ]


def test_tie_breaks_by_membership_id() -> None:
    result = rank_candidates(POLICY_V1, REQ, (candidate(MEMBER_B), candidate(MEMBER_A)))

    assert [row.membership_id for row in result] == [MEMBER_A, MEMBER_B]


def test_greedy_selection_covers_multiple_requirements_without_exceeding_capacity() -> None:
    writing = TeamRequirement(
        id=UUID("00000000-0000-0000-0000-000000000006"),
        organization_id=ORGANIZATION_ID,
        project_week_id=WEEK_ID,
        skill_label="writing",
        minimum_level=SkillLevel.LEVEL_1,
        required_effort_hours=Decimal("8"),
    )
    member = candidate(MEMBER_A, residual=16)
    member = Candidate(
        membership_id=member.membership_id,
        organization_id=member.organization_id,
        active=member.active,
        policy_allowed=member.policy_allowed,
        skills=(
            *member.skills,
            CandidateSkill(
                skill_label="writing",
                verified_skill=VerifiedPersonSkill(
                    id=UUID("00000000-0000-0000-0000-000000000020"),
                    organization_id=ORGANIZATION_ID,
                    membership_id=MEMBER_A,
                    skill_id=WRITING_SKILL_ID,
                    level=SkillLevel.LEVEL_5,
                    verified_by_membership_id=MEMBER_C,
                    verified_at=NOW,
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ),
        ),
        workloads=member.workloads,
        evidence_ratio=member.evidence_ratio,
        familiarity_ratio=member.familiarity_ratio,
    )

    result = select_team(POLICY_V1, requirements=(writing, REQ), candidates=(member,))

    allocations = [
        (item.requirement_id, item.membership_id, item.allocated_effort_hours)
        for item in result.allocations
    ]
    assert allocations == [
        (REQ.id, MEMBER_A, Decimal("8")),
        (writing.id, MEMBER_A, Decimal("8")),
    ]
    assert result.uncovered == ()


def test_capacity_exhaustion_returns_uncovered_demand_and_alternatives() -> None:
    second = TeamRequirement(
        id=UUID("00000000-0000-0000-0000-000000000007"),
        organization_id=ORGANIZATION_ID,
        project_week_id=WEEK_ID,
        skill_label="analysis",
        minimum_level=SkillLevel.LEVEL_3,
        required_effort_hours=Decimal("8"),
    )

    result = select_team(
        POLICY_V1,
        requirements=(REQ, second),
        candidates=(candidate(MEMBER_A, residual=8),),
    )

    assert len(result.allocations) == 1
    assert result.uncovered[0].requirement_id == second.id
    assert result.uncovered[0].uncovered_effort_hours == Decimal("8")
    assert result.alternatives[0].requirement_id == second.id
    assert result.alternatives[0].candidate_membership_ids == (MEMBER_A,)


def test_selection_allocates_scarce_requirements_before_broad_requirements() -> None:
    writing = TeamRequirement(
        id=UUID("00000000-0000-0000-0000-000000000008"),
        organization_id=ORGANIZATION_ID,
        project_week_id=WEEK_ID,
        skill_label="writing",
        minimum_level=SkillLevel.LEVEL_1,
        required_effort_hours=Decimal("8"),
    )
    candidate_a = candidate(MEMBER_A, residual=8)
    candidate_a = Candidate(
        membership_id=candidate_a.membership_id,
        organization_id=candidate_a.organization_id,
        active=candidate_a.active,
        policy_allowed=candidate_a.policy_allowed,
        skills=(
            *candidate_a.skills,
            CandidateSkill(
                skill_label="writing",
                verified_skill=VerifiedPersonSkill(
                    id=UUID("00000000-0000-0000-0000-000000000021"),
                    organization_id=ORGANIZATION_ID,
                    membership_id=MEMBER_A,
                    skill_id=WRITING_SKILL_ID,
                    level=SkillLevel.LEVEL_5,
                    verified_by_membership_id=MEMBER_C,
                    verified_at=NOW,
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ),
        ),
        workloads=candidate_a.workloads,
        evidence_ratio=candidate_a.evidence_ratio,
        familiarity_ratio=candidate_a.familiarity_ratio,
    )

    result = select_team(
        POLICY_V1,
        requirements=(REQ, writing),
        candidates=(candidate_a, candidate(MEMBER_B, residual=8)),
    )

    assert [(item.requirement_id, item.membership_id) for item in result.allocations] == [
        (writing.id, MEMBER_A),
        (REQ.id, MEMBER_B),
    ]
    assert result.uncovered == ()


def test_selection_accepts_one_pass_requirement_iterables() -> None:
    result = select_team(
        POLICY_V1,
        requirements=(requirement for requirement in (REQ,)),
        candidates=(candidate(MEMBER_A),),
    )

    assert result.allocations[0].requirement_id == REQ.id


@pytest.mark.parametrize("_iteration", range(25))
def test_selection_is_repeatable_for_twenty_five_runs(_iteration: int) -> None:
    result = select_team(POLICY_V1, requirements=(REQ,), candidates=CANDIDATES)

    assert result == select_team(
        POLICY_V1,
        requirements=(REQ,),
        candidates=tuple(reversed(CANDIDATES)),
    )
