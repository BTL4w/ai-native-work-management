"""Deterministic policy for every Task assignment entry point."""

from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.work.planning.assignment.application.assignment_service import (
    AssignmentError,
    AssignmentPolicyFacts,
    validate_assignment_policy,
)


def valid_facts() -> AssignmentPolicyFacts:
    return AssignmentPolicyFacts(
        organization_id=uuid4(),
        assignee_organization_id=None,
        membership_active=True,
        user_active=True,
        active_project_team_membership=True,
        hard_policy_allowed=True,
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"assignee_organization_id": uuid4()}, "ASSIGNEE_OUTSIDE_ORGANIZATION"),
        ({"membership_active": False}, "ASSIGNEE_INACTIVE"),
        ({"user_active": False}, "ASSIGNEE_INACTIVE"),
        ({"active_project_team_membership": False}, "ASSIGNEE_NOT_ON_PROJECT_TEAM"),
        ({"hard_policy_allowed": False}, "ASSIGNMENT_POLICY_DENIED"),
    ],
)
def test_assignment_policy_rejects_each_hard_constraint(
    change: dict[str, object], code: str
) -> None:
    facts = valid_facts()
    facts = replace(facts, assignee_organization_id=facts.organization_id)
    facts = replace(facts, **change)

    with pytest.raises(AssignmentError, match=code):
        validate_assignment_policy(facts)


def test_assignment_policy_accepts_active_same_tenant_project_team_member() -> None:
    facts = valid_facts()
    facts = AssignmentPolicyFacts(
        organization_id=facts.organization_id,
        assignee_organization_id=facts.organization_id,
        membership_active=True,
        user_active=True,
        active_project_team_membership=True,
        hard_policy_allowed=True,
    )

    validate_assignment_policy(facts)
