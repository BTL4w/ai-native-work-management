"""Deterministic Phase 2 capability and role boundary."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PlanningPolicyDecision:
    outcome: Literal["ALLOW", "FORBIDDEN", "UNSUPPORTED"]
    code: str | None = None


_UNSUPPORTED_PHRASES = (
    "recommend assignee",
    "recommend the best assignee",
    "assignee recommendation",
    "đề xuất người phụ trách",
    "đề xuất assignee",
    "xếp hạng người",
    "workload",
    "capacity",
    "daily update",
    "cập nhật hàng ngày",
    "risk report",
    "risk analysis",
    "báo cáo rủi ro",
    "management report",
    "báo cáo quản lý",
)


def evaluate_planning_policy(*, actor_role: str, user_brief: str) -> PlanningPolicyDecision:
    """Allow Manager planning only and safely reject future capabilities."""

    if actor_role not in {"ADMIN", "MANAGER"}:
        return PlanningPolicyDecision(outcome="FORBIDDEN", code="PLANNING_FORBIDDEN")
    normalized = " ".join(user_brief.casefold().split())
    if any(phrase in normalized for phrase in _UNSUPPORTED_PHRASES):
        return PlanningPolicyDecision(
            outcome="UNSUPPORTED",
            code="UNSUPPORTED_CAPABILITY",
        )
    return PlanningPolicyDecision(outcome="ALLOW")
