"""Verify that model explanations are grounded in deterministic projections."""

import re
from decimal import Decimal

from work_management_ai.agents.assignment.contracts import (
    AssignmentExplanation,
    ProjectWorkloadSnapshot,
    TeamRecommendationSnapshot,
    WorkloadExplanation,
)

_PROTECTED_TERMS = frozenset(
    {
        "age",
        "ethnicity",
        "gender",
        "race",
        "religion",
        "salary",
        "tuổi",
        "giới tính",
        "lương",
        "sắc tộc",
        "tôn giáo",
    }
)


class AssignmentExplanationError(ValueError):
    pass


def _reject_protected_text(values: tuple[str, ...]) -> None:
    normalized = "\n".join(values).casefold()
    if any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized) for term in _PROTECTED_TERMS):
        raise AssignmentExplanationError("PROTECTED_ATTRIBUTE")


def _canonical_number(value: Decimal | int) -> str:
    if isinstance(value, int):
        return str(value)
    normalized = format(value, "f").rstrip("0").rstrip(".")
    return normalized or "0"


def _reject_unsupported_numbers(text: str, allowed: tuple[Decimal | int | None, ...]) -> None:
    asserted = {
        _canonical_number(Decimal(match.group(0)))
        for match in re.finditer(r"(?<!\w)\d+(?:\.\d+)?(?!\w)", text)
    }
    permitted = {_canonical_number(value) for value in allowed if value is not None}
    if not asserted.issubset(permitted):
        raise AssignmentExplanationError("NUMERIC_FACT_UNSUPPORTED")


def verify_assignment_explanation(
    snapshot: TeamRecommendationSnapshot, explanation: AssignmentExplanation
) -> None:
    if (
        explanation.recommendation_id != snapshot.recommendation_id
        or explanation.version != snapshot.version
    ):
        raise AssignmentExplanationError("RECOMMENDATION_REFERENCE_UNSUPPORTED")
    selected = {item.membership_id: item for item in snapshot.selected_members}
    alternatives = {
        (item.membership_id, item.requirement_id): item
        for item in snapshot.alternatives
        if item.eligible
    }
    all_evidence = {
        evidence.evidence_id
        for item in (*snapshot.selected_members, *snapshot.alternatives)
        for evidence in item.evidence
    }
    reason_ids = tuple(item.membership_id for item in explanation.member_reasons)
    if len(reason_ids) != len(set(reason_ids)) or set(reason_ids) != set(selected):
        raise AssignmentExplanationError("SELECTED_MEMBER_COVERAGE")
    texts: list[str] = []
    for reason in explanation.member_reasons:
        source = selected.get(reason.membership_id)
        if source is None:
            raise AssignmentExplanationError("MEMBER_UNSUPPORTED")
        if (
            reason.display_name != source.display_name
            or reason.requirement_ids != source.requirement_ids
            or reason.total_points != source.scores.total_points
            or reason.workload_ratio != source.workload_ratio
        ):
            raise AssignmentExplanationError("MEMBER_FACT_UNSUPPORTED")
        permitted = {item.evidence_id for item in source.evidence}
        if not set(reason.evidence_ids).issubset(permitted):
            raise AssignmentExplanationError("EVIDENCE_UNSUPPORTED")
        _reject_unsupported_numbers(
            reason.text,
            (source.scores.total_points, source.workload_ratio),
        )
        texts.append(reason.text)
    for alternative in explanation.alternatives:
        source = alternatives.get((alternative.membership_id, alternative.requirement_id))
        if source is None:
            raise AssignmentExplanationError("ALTERNATIVE_UNSUPPORTED")
        if (
            alternative.display_name != source.display_name
            or alternative.total_points != source.scores.total_points
        ):
            raise AssignmentExplanationError("ALTERNATIVE_FACT_UNSUPPORTED")
        permitted = {item.evidence_id for item in source.evidence}
        if not set(alternative.evidence_ids).issubset(permitted):
            raise AssignmentExplanationError("EVIDENCE_UNSUPPORTED")
        _reject_unsupported_numbers(alternative.text, (source.scores.total_points,))
        texts.append(alternative.text)
    for risk in explanation.risks:
        if not set(risk.evidence_ids).issubset(all_evidence):
            raise AssignmentExplanationError("EVIDENCE_UNSUPPORTED")
        _reject_unsupported_numbers(
            risk.text,
            tuple(
                value
                for item in (*snapshot.selected_members, *snapshot.alternatives)
                for value in (item.scores.total_points, item.workload_ratio)
            ),
        )
        texts.append(risk.text)
    if set(explanation.uncovered_requirement_ids) != set(snapshot.uncovered_requirement_ids):
        raise AssignmentExplanationError("UNCOVERED_REQUIREMENT_UNSUPPORTED")
    _reject_protected_text(tuple(texts))


def verify_workload_explanation(
    snapshot: ProjectWorkloadSnapshot, explanation: WorkloadExplanation
) -> None:
    if explanation.project_id != snapshot.project_id:
        raise AssignmentExplanationError("PROJECT_REFERENCE_UNSUPPORTED")
    workloads = {(item.membership_id, item.project_week_id): item for item in snapshot.workloads}
    reason_keys = tuple(
        (item.membership_id, item.project_week_id) for item in explanation.member_reasons
    )
    if len(reason_keys) != len(set(reason_keys)) or set(reason_keys) != set(workloads):
        raise AssignmentExplanationError("WORKLOAD_COVERAGE")
    texts: list[str] = []
    for reason in explanation.member_reasons:
        source = workloads.get((reason.membership_id, reason.project_week_id))
        if source is None or reason.workload_ratio != source.workload_ratio:
            raise AssignmentExplanationError("WORKLOAD_FACT_UNSUPPORTED")
        _reject_unsupported_numbers(
            reason.text,
            (
                source.workload_ratio,
                source.effective_capacity_hours,
                source.allocated_effort_hours,
                source.residual_capacity_hours,
            ),
        )
        texts.append(reason.text)
    _reject_protected_text(tuple(texts))


def verify_explanation_context(snapshot: TeamRecommendationSnapshot) -> None:
    """Reject sensitive evidence before it can be serialized into a model prompt."""

    summaries = tuple(
        evidence.summary
        for item in (*snapshot.selected_members, *snapshot.alternatives)
        for evidence in item.evidence
    )
    _reject_protected_text(summaries)
