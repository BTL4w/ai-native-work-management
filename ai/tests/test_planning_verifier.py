"""Deterministic planning verifier behavior."""

from copy import deepcopy
from typing import cast

import pytest

from work_management_ai.schemas.planning import PlanningModelOutput
from work_management_ai.workflows.planning.verifier import (
    MAX_ACCEPTANCE_CRITERIA_PER_TASK,
    MAX_DEPENDENCIES,
    MAX_MILESTONES,
    MAX_TASKS,
    PlanningVerificationContext,
    verify_plan,
)


def valid_plan_data() -> dict[str, object]:
    return {
        "project": {
            "title": "Customer conference",
            "description": None,
            "start_date": "2026-08-10",
            "due_date": "2026-09-30",
        },
        "goal": {
            "title": "Engage customers",
            "description": None,
            "expected_outcomes": ["Three hundred attendees participate"],
            "target_date": "2026-09-30",
        },
        "milestones": [
            {
                "ref": "m1",
                "title": "Venue confirmed",
                "description": None,
                "due_date": "2026-09-01",
            }
        ],
        "project_weeks": [
            {
                "ref": "w1",
                "week_number": 1,
                "start_date": "2026-08-10",
                "end_date": "2026-08-16",
                "objective": "Prepare venue sourcing",
            },
            {
                "ref": "w2",
                "week_number": 2,
                "start_date": "2026-08-17",
                "end_date": "2026-08-25",
                "objective": "Confirm venue",
            },
        ],
        "tasks": [
            {
                "ref": "t1",
                "project_week_ref": "w2",
                "milestone_ref": "m1",
                "title": "Confirm venue",
                "description": None,
                "due_date": "2026-08-25",
                "assignee_membership_id": None,
                "required_skill_labels": ["vendor negotiation"],
                "estimated_effort_hours": 16,
                "acceptance_criteria": ["Signed venue agreement is available"],
            }
        ],
        "dependencies": [],
        "assumptions": [],
    }


def verification_context() -> PlanningVerificationContext:
    return PlanningVerificationContext()


def assigned_plan_data() -> dict[str, object]:
    return valid_plan_data()


def test_verifier_accepts_unassigned_weekly_task() -> None:
    plan = PlanningModelOutput.model_validate(valid_plan_data())

    result = verify_plan(plan, verification_context())

    assert result.errors == ()
    assert result.can_approve is True


def test_schema_rejects_ai_assignee() -> None:
    data = valid_plan_data()
    tasks = cast(list[dict[str, object]], data["tasks"])
    tasks[0]["assignee_membership_id"] = "00000000-0000-0000-0000-000000000111"

    with pytest.raises(ValueError):
        PlanningModelOutput.model_validate(data)


def test_verifier_accepts_exactly_one_goal_and_resolves_temporary_refs() -> None:
    plan = PlanningModelOutput.model_validate(assigned_plan_data())

    result = verify_plan(plan, verification_context())

    assert plan.goal.title == "Engage customers"
    assert result.errors == ()
    assert result.can_approve is True


@pytest.mark.parametrize(
    ("dependencies", "expected_codes"),
    [
        ([{"predecessor_ref": "t1", "successor_ref": "t1"}], ["DEPENDENCY_SELF_EDGE"]),
        (
            [
                {"predecessor_ref": "t1", "successor_ref": "t2"},
                {"predecessor_ref": "t1", "successor_ref": "t2"},
            ],
            ["DEPENDENCY_DUPLICATE"],
        ),
        (
            [
                {"predecessor_ref": "t1", "successor_ref": "t2"},
                {"predecessor_ref": "t2", "successor_ref": "t1"},
            ],
            ["DEPENDENCY_CYCLE"],
        ),
    ],
)
def test_verifier_rejects_invalid_dependency_edges(
    dependencies: list[dict[str, str]],
    expected_codes: list[str],
) -> None:
    data = assigned_plan_data()
    tasks = cast(list[dict[str, object]], data["tasks"])
    tasks.append(
        {
            **deepcopy(tasks[0]),
            "ref": "t2",
            "title": "Invite customers",
        }
    )
    data["dependencies"] = dependencies

    result = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    assert [item.code for item in result.errors] == expected_codes


def test_verifier_rejects_task_after_milestone_and_milestone_after_project() -> None:
    data = assigned_plan_data()
    milestones = cast(list[dict[str, object]], data["milestones"])
    tasks = cast(list[dict[str, object]], data["tasks"])
    milestones[0]["due_date"] = "2026-10-01"
    tasks[0]["due_date"] = "2026-10-02"

    result = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    assert [(item.path, item.code) for item in result.errors] == [
        ("milestones[m1].due_date", "MILESTONE_AFTER_PROJECT"),
        ("tasks[t1].due_date", "TASK_AFTER_MILESTONE"),
        ("tasks[t1].due_date", "TASK_OUTSIDE_PROJECT_WEEK"),
    ]


def test_verifier_rejects_project_date_order_and_goal_after_project() -> None:
    data = assigned_plan_data()
    project = cast(dict[str, object], data["project"])
    goal = cast(dict[str, object], data["goal"])
    project["start_date"] = "2026-10-01"
    project["due_date"] = "2026-09-30"
    goal["target_date"] = "2026-10-02"

    result = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    assert [(item.path, item.code) for item in result.errors] == [
        ("goal.target_date", "GOAL_AFTER_PROJECT"),
        ("project.start_date", "PROJECT_DATE_ORDER"),
        ("project_weeks[w1].start_date", "PROJECT_WEEK_OUTSIDE_PROJECT"),
        ("project_weeks[w2].start_date", "PROJECT_WEEK_OUTSIDE_PROJECT"),
    ]


def test_verifier_rejects_duplicate_normalized_acceptance_criteria() -> None:
    data = assigned_plan_data()
    tasks = cast(list[dict[str, object]], data["tasks"])
    tasks[0]["acceptance_criteria"] = [
        " Signed venue agreement   is available ",
        "signed venue agreement is AVAILABLE",
    ]

    result = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    assert [(item.path, item.code) for item in result.errors] == [
        ("tasks[t1].acceptance_criteria[1]", "ACCEPTANCE_CRITERION_DUPLICATE")
    ]


def test_verifier_keeps_relations_inside_the_proposed_project_context() -> None:
    data = assigned_plan_data()
    tasks = cast(list[dict[str, object]], data["tasks"])
    tasks[0]["milestone_ref"] = "other-project-milestone"
    data["dependencies"] = [{"predecessor_ref": "other-project-task", "successor_ref": "t1"}]

    result = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    assert [(item.path, item.code) for item in result.errors] == [
        ("dependencies[0].predecessor_ref", "TASK_REF_OUTSIDE_CONTEXT"),
        ("tasks[t1].milestone_ref", "MILESTONE_REF_OUTSIDE_CONTEXT"),
    ]


@pytest.mark.parametrize(
    ("field", "count", "expected_code"),
    [
        ("milestones", MAX_MILESTONES + 1, "MILESTONE_LIMIT_EXCEEDED"),
        ("tasks", MAX_TASKS + 1, "TASK_LIMIT_EXCEEDED"),
        ("dependencies", MAX_DEPENDENCIES + 1, "DEPENDENCY_LIMIT_EXCEEDED"),
        (
            "acceptance_criteria",
            MAX_ACCEPTANCE_CRITERIA_PER_TASK + 1,
            "ACCEPTANCE_CRITERIA_LIMIT_EXCEEDED",
        ),
    ],
)
def test_verifier_enforces_proposal_size_limits(
    field: str,
    count: int,
    expected_code: str,
) -> None:
    data = assigned_plan_data()
    tasks = cast(list[dict[str, object]], data["tasks"])
    milestones = cast(list[dict[str, object]], data["milestones"])
    if field == "milestones":
        data[field] = [{**deepcopy(milestones[0]), "ref": f"m{index}"} for index in range(count)]
    elif field == "tasks":
        data[field] = [{**deepcopy(tasks[0]), "ref": f"t{index}"} for index in range(count)]
    elif field == "dependencies":
        tasks.append({**deepcopy(tasks[0]), "ref": "t2"})
        data[field] = [{"predecessor_ref": "t1", "successor_ref": "t2"} for _ in range(count)]
    else:
        tasks[0][field] = [f"criterion {index}" for index in range(count)]

    result = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    assert expected_code in {item.code for item in result.errors}


def test_verifier_returns_stably_ordered_errors() -> None:
    data = valid_plan_data()
    tasks = cast(list[dict[str, object]], data["tasks"])
    tasks[0]["milestone_ref"] = "missing"
    tasks[0]["acceptance_criteria"] = ["Same", " same "]

    first = verify_plan(PlanningModelOutput.model_validate(data), verification_context())
    second = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    first_pairs = [(item.path, item.code) for item in first.errors]
    assert first_pairs == sorted(first_pairs)
    assert first.errors == second.errors


def test_warning_does_not_block_approval() -> None:
    data = assigned_plan_data()
    tasks = cast(list[dict[str, object]], data["tasks"])
    tasks[0]["acceptance_criteria"] = []

    result = verify_plan(PlanningModelOutput.model_validate(data), verification_context())

    assert [(item.path, item.code) for item in result.warnings] == [
        ("tasks[t1].acceptance_criteria", "ACCEPTANCE_CRITERIA_MISSING")
    ]
    assert result.errors == ()
    assert result.can_approve is True
