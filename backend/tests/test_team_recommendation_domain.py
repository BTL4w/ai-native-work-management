"""Immutable revisions reject invalid choices before producing any version."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.modules.work.planning.assignment.application.ranking_preview import (
    CandidateRankingPreview,
    RankingAllocationPreview,
    RankingPreview,
)
from app.modules.work.planning.assignment.domain.recommendations import (
    CandidateOverride,
    RecommendationDiff,
    RecommendationError,
    RequirementDemand,
    build_version,
)


def inputs() -> tuple[RankingPreview, tuple[RequirementDemand, ...], UUID, UUID]:
    requirement, member, other, week = (uuid4() for _ in range(4))
    score = CandidateRankingPreview(
        requirement,
        member,
        "Member",
        True,
        (),
        Decimal(".5"),
        Decimal(".3"),
        Decimal("0"),
        Decimal("0"),
        Decimal(".8"),
        40,
        40,
        (),
    )
    preview = RankingPreview(
        uuid4(),
        2,
        "ranking-v1",
        "DETERMINISTIC",
        (score, replace(score, membership_id=other, total_points=Decimal(".7"))),
        (RankingAllocationPreview(requirement, member, Decimal("8")),),
        (),
    )
    demands = (RequirementDemand(requirement, week, Decimal("8")),)
    return preview, demands, member, other


def test_revision_preserves_v1_and_explains_replacement():
    preview, demands, member, other = inputs()
    first = build_version(recommendation_id=uuid4(), preview=preview, demands=demands)
    revised = build_version(
        recommendation_id=first.recommendation_id,
        preview=preview,
        demands=demands,
        base=first,
        overrides=(CandidateOverride(demands[0].requirement_id, other, "Experience"),),
    )
    assert first.version == 1 and first.selections[0].membership_id == member
    assert revised.version == 2 and revised.selections[0].membership_id == other
    diff = cast(RecommendationDiff, revised.diff)
    assert diff.removed_membership_ids == (member,)
    assert diff.added_membership_ids == (other,)
    with pytest.raises(FrozenInstanceError):
        setattr(first, "version", 3)  # noqa: B010


@pytest.mark.parametrize(
    "kind,code",
    [
        ("ineligible", "CANDIDATE_INELIGIBLE"),
        ("reason", "OVERRIDE_REASON_REQUIRED"),
        ("stale", "STALE_REQUIREMENTS"),
    ],
)
def test_invalid_revision_produces_no_version(kind: str, code: str) -> None:
    preview, demands, _, other = inputs()
    first = build_version(recommendation_id=uuid4(), preview=preview, demands=demands)
    if kind == "ineligible":
        preview = replace(
            preview,
            candidates=(preview.candidates[0], replace(preview.candidates[1], eligible=False)),
        )
    if kind == "stale":
        preview = replace(preview, requirement_version=3)
    with pytest.raises(RecommendationError, match=code):
        build_version(
            recommendation_id=first.recommendation_id,
            preview=preview,
            demands=demands,
            base=first,
            overrides=(CandidateOverride(demands[0].requirement_id, other),),
        )
    assert first.version == 1


def test_removal_exposes_uncovered_demand_and_partial_allocations_are_decimal():
    preview, demands, member, other = inputs()
    first = build_version(recommendation_id=uuid4(), preview=preview, demands=demands)
    empty = build_version(
        recommendation_id=first.recommendation_id,
        preview=preview,
        demands=demands,
        base=first,
        overrides=(),
    )
    assert empty.selections == () and empty.uncovered[0].uncovered_effort_hours == Decimal("8")
    split = build_version(
        recommendation_id=first.recommendation_id,
        preview=preview,
        demands=demands,
        base=first,
        overrides=(
            CandidateOverride(demands[0].requirement_id, member, None, Decimal("3.5")),
            CandidateOverride(demands[0].requirement_id, other, "Shared coverage", Decimal("4.5")),
        ),
    )
    assert sorted(x.allocated_effort_hours for x in split.selections) == [
        Decimal("3.5"),
        Decimal("4.5"),
    ]
    assert split.uncovered == ()


def test_versions_canonicalize_all_snapshot_collections():
    preview, demands, member, other = inputs()
    reversed_preview = replace(
        preview,
        candidates=tuple(reversed(preview.candidates)),
        allocations=(
            replace(
                preview.allocations[0],
                membership_id=other,
                allocated_effort_hours=Decimal("3"),
            ),
            replace(
                preview.allocations[0],
                membership_id=member,
                allocated_effort_hours=Decimal("5"),
            ),
        ),
    )

    version = build_version(recommendation_id=uuid4(), preview=reversed_preview, demands=demands)

    assert tuple(item.membership_id for item in version.alternatives) == (member, other)
    assert tuple(item.membership_id for item in version.selections) == tuple(
        sorted((member, other), key=str)
    )


def test_snapshot_collections_are_deeply_immutable_tuples():
    preview, demands, *_ = inputs()
    version = build_version(recommendation_id=uuid4(), preview=preview, demands=demands)

    assert isinstance(version.alternatives, tuple)
    assert isinstance(version.selections, tuple)
    assert isinstance(version.alternatives[0].hard_failure_codes, tuple)
    assert isinstance(version.alternatives[0].evidence, tuple)


def test_unchanged_deterministic_split_revalidates_without_manual_override_reason() -> None:
    preview, demands, member, other = inputs()
    split_preview = replace(
        preview,
        allocations=(
            RankingAllocationPreview(demands[0].requirement_id, member, Decimal("4")),
            RankingAllocationPreview(demands[0].requirement_id, other, Decimal("4")),
        ),
    )
    proposed = build_version(recommendation_id=uuid4(), preview=split_preview, demands=demands)

    checked = build_version(
        recommendation_id=proposed.recommendation_id,
        preview=split_preview,
        demands=demands,
        overrides=tuple(
            CandidateOverride(
                selection.requirement_id,
                selection.membership_id,
                selection.override_reason,
                selection.allocated_effort_hours,
            )
            for selection in proposed.selections
        ),
        enforce_manual_override_reasons=False,
    )

    assert checked.selections == proposed.selections
