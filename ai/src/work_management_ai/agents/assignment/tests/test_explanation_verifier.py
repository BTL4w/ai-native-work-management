from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from work_management_ai.agents.assignment.contracts import (
    AssignmentExplanation,
    CandidateSnapshot,
    EvidenceSnapshot,
    GroundedAlternative,
    GroundedClaim,
    MemberReason,
    MemberWorkloadReason,
    ProjectWorkloadSnapshot,
    ScoreBreakdown,
    SelectedMemberSnapshot,
    TeamRecommendationSnapshot,
    WorkloadExplanation,
    WorkloadSnapshot,
)
from work_management_ai.agents.assignment.evaluators.explanation import (
    AssignmentExplanationError,
    verify_assignment_explanation,
    verify_workload_explanation,
)


def _snapshot() -> TeamRecommendationSnapshot:
    organization_id = uuid4()
    project_id = uuid4()
    recommendation_id = uuid4()
    requirement_id = uuid4()
    selected_id = uuid4()
    alternative_id = uuid4()
    evidence = EvidenceSnapshot(
        evidence_id="evidence:launch:v1",
        summary="Delivered a comparable launch.",
        source_resource_type="TASK",
        source_resource_id=uuid4(),
        source_resource_version=1,
    )
    selected = SelectedMemberSnapshot(
        membership_id=selected_id,
        display_name="Lan",
        requirement_ids=(requirement_id,),
        scores=ScoreBreakdown(
            skill_points=Decimal("45.00"),
            capacity_points=Decimal("24.00"),
            evidence_points=Decimal("12.00"),
            familiarity_points=Decimal("4.00"),
            total_points=Decimal("85.00"),
        ),
        evidence=(evidence,),
        workload_ratio=Decimal("0.60"),
        warning_codes=(),
    )
    alternative = CandidateSnapshot(
        membership_id=alternative_id,
        display_name="Minh",
        requirement_id=requirement_id,
        eligible=True,
        hard_failure_codes=(),
        scores=ScoreBreakdown(
            skill_points=Decimal("40.00"),
            capacity_points=Decimal("25.00"),
            evidence_points=Decimal("10.00"),
            familiarity_points=Decimal("3.00"),
            total_points=Decimal("78.00"),
        ),
        evidence=(),
        workload_ratio=Decimal("0.50"),
    )
    return TeamRecommendationSnapshot(
        organization_id=organization_id,
        project_id=project_id,
        requirement_set_id=uuid4(),
        requirement_version=2,
        recommendation_id=recommendation_id,
        version=1,
        status="PROPOSED",
        policy_version="ranking-v1",
        selected_members=(selected,),
        alternatives=(alternative,),
        uncovered_requirement_ids=(),
        observed_at=datetime.now(UTC),
    )


def _explanation(snapshot: TeamRecommendationSnapshot) -> AssignmentExplanation:
    selected = snapshot.selected_members[0]
    alternative = snapshot.alternatives[0]
    return AssignmentExplanation(
        recommendation_id=snapshot.recommendation_id,
        version=snapshot.version,
        member_reasons=(
            MemberReason(
                membership_id=selected.membership_id,
                display_name=selected.display_name,
                requirement_ids=selected.requirement_ids,
                total_points=selected.scores.total_points,
                workload_ratio=selected.workload_ratio,
                evidence_ids=(selected.evidence[0].evidence_id,),
                text="Lan fits the verified requirement and available workload.",
            ),
        ),
        risks=(
            GroundedClaim(
                text="Capacity should be monitored.",
                evidence_ids=(selected.evidence[0].evidence_id,),
            ),
        ),
        alternatives=(
            GroundedAlternative(
                membership_id=alternative.membership_id,
                display_name=alternative.display_name,
                requirement_id=alternative.requirement_id,
                total_points=alternative.scores.total_points,
                evidence_ids=(),
                text="Minh is an eligible alternative.",
            ),
        ),
        uncovered_requirement_ids=(),
    )


def test_verifier_accepts_only_exact_deterministic_names_scores_and_evidence() -> None:
    snapshot = _snapshot()

    verify_assignment_explanation(snapshot, _explanation(snapshot))


def test_verifier_allows_words_that_only_contain_a_protected_term_fragment() -> None:
    snapshot = _snapshot()
    explanation = _explanation(snapshot)
    reason = explanation.member_reasons[0].model_copy(
        update={"text": "Lan managed comparable work."}
    )

    verify_assignment_explanation(
        snapshot, explanation.model_copy(update={"member_reasons": (reason,)})
    )


def test_verifier_rejects_unasserted_numeric_claims() -> None:
    snapshot = _snapshot()
    explanation = _explanation(snapshot)
    reason = explanation.member_reasons[0].model_copy(update={"text": "Lan has a score of 99."})

    with pytest.raises(AssignmentExplanationError, match="NUMERIC_FACT_UNSUPPORTED"):
        verify_assignment_explanation(
            snapshot, explanation.model_copy(update={"member_reasons": (reason,)})
        )


def test_verifier_accepts_supported_numeric_claim_with_snapshot_precision() -> None:
    snapshot = _snapshot()
    explanation = _explanation(snapshot)
    reason = explanation.member_reasons[0].model_copy(
        update={"text": "Lan has the verified score 85.00 and workload ratio 0.60."}
    )

    verify_assignment_explanation(
        snapshot, explanation.model_copy(update={"member_reasons": (reason,)})
    )


def test_verifier_requires_one_reason_for_every_selected_member() -> None:
    snapshot = _snapshot()

    with pytest.raises(AssignmentExplanationError, match="SELECTED_MEMBER_COVERAGE"):
        verify_assignment_explanation(
            snapshot, _explanation(snapshot).model_copy(update={"member_reasons": ()})
        )


def test_workload_verifier_requires_every_deterministic_row() -> None:
    row = WorkloadSnapshot(
        membership_id=uuid4(),
        project_week_id=uuid4(),
        effective_capacity_hours=40,
        allocated_effort_hours=24,
        residual_capacity_hours=16,
        workload_ratio=Decimal("0.60"),
    )
    snapshot = ProjectWorkloadSnapshot(
        organization_id=uuid4(),
        project_id=uuid4(),
        workloads=(row,),
        observed_at=datetime.now(UTC),
    )
    valid = WorkloadExplanation(
        project_id=snapshot.project_id,
        member_reasons=(
            MemberWorkloadReason(
                membership_id=row.membership_id,
                project_week_id=row.project_week_id,
                workload_ratio=row.workload_ratio,
                text="16 hours remain.",
            ),
        ),
    )

    verify_workload_explanation(snapshot, valid)
    with pytest.raises(AssignmentExplanationError, match="WORKLOAD_COVERAGE"):
        verify_workload_explanation(snapshot, valid.model_copy(update={"member_reasons": ()}))


@pytest.mark.parametrize(
    "mutation",
    ["person", "score", "evidence", "requirement", "alternative", "uncovered"],
)
def test_verifier_rejects_unsupported_deterministic_claims(mutation: str) -> None:
    snapshot = _snapshot()
    explanation = _explanation(snapshot)
    reason = explanation.member_reasons[0]
    alternative = explanation.alternatives[0]
    if mutation == "person":
        reason = reason.model_copy(update={"membership_id": uuid4()})
    elif mutation == "score":
        reason = reason.model_copy(update={"total_points": Decimal("99.00")})
    elif mutation == "evidence":
        reason = reason.model_copy(update={"evidence_ids": ("evidence:invented:v1",)})
    elif mutation == "requirement":
        reason = reason.model_copy(update={"requirement_ids": (uuid4(),)})
    elif mutation == "alternative":
        alternative = alternative.model_copy(update={"display_name": "Invented Name"})
    else:
        explanation = explanation.model_copy(update={"uncovered_requirement_ids": (uuid4(),)})
    explanation = explanation.model_copy(
        update={"member_reasons": (reason,), "alternatives": (alternative,)}
    )

    with pytest.raises(AssignmentExplanationError):
        verify_assignment_explanation(snapshot, explanation)


@pytest.mark.parametrize("protected_text", ["salary", "tuổi", "gender", "ethnicity"])
def test_verifier_rejects_protected_attribute_leakage(protected_text: str) -> None:
    snapshot = _snapshot()
    explanation = _explanation(snapshot)
    reason = explanation.member_reasons[0].model_copy(
        update={"text": f"Selected using {protected_text}."}
    )

    with pytest.raises(AssignmentExplanationError, match="PROTECTED_ATTRIBUTE"):
        verify_assignment_explanation(
            snapshot, explanation.model_copy(update={"member_reasons": (reason,)})
        )
