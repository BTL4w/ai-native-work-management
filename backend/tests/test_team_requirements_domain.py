"""Tests for deterministic project-team requirement derivation."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.modules.people_capacity.domain.skills import SkillLevel
from app.modules.work.domain.tasks import Task, TaskStatus
from app.modules.work.planning.assignment.domain.requirements import (
    IncompleteRequirement,
    TeamRequirement,
    derive_requirement_draft,
)

ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000002")
WEEK_ONE_ID = UUID("00000000-0000-0000-0000-000000000003")
WEEK_TWO_ID = UUID("00000000-0000-0000-0000-000000000004")
NOW = datetime(2026, 9, 4, tzinfo=UTC)


def task(
    *,
    title: str,
    skill_labels: tuple[str, ...],
    effort: Decimal | None,
    project_week_id: UUID | None = WEEK_ONE_ID,
    task_id: UUID | None = None,
) -> Task:
    return Task(
        id=task_id or uuid4(),
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        milestone_id=None,
        title=title,
        description=None,
        assignee_membership_id=None,
        assignee_display_name=None,
        status=TaskStatus.TO_DO,
        due_date=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
        project_week_id=project_week_id,
        required_skill_labels=skill_labels,
        estimated_effort_hours=None if effort is None else int(effort),
    )


def test_missing_task_skill_becomes_explicit_incomplete_requirement() -> None:
    result = derive_requirement_draft(
        tasks=(task(title="Discovery", skill_labels=(), effort=Decimal("8")),)
    )

    assert result.incomplete_items[0].reason == "REQUIRED_SKILL_MISSING"
    assert result.incomplete_items[0].task_title == "Discovery"
    assert result.confirmable is False
    assert result.requirements == ()


def test_each_missing_task_fact_becomes_an_explicit_incomplete_item() -> None:
    task_id = UUID("00000000-0000-0000-0000-000000000009")

    result = derive_requirement_draft(
        tasks=(
            task(
                task_id=task_id,
                title="Incomplete discovery",
                skill_labels=(),
                effort=None,
                project_week_id=None,
            ),
        )
    )

    assert result.incomplete_items == (
        IncompleteRequirement(task_id, "Incomplete discovery", "ESTIMATED_EFFORT_MISSING"),
        IncompleteRequirement(task_id, "Incomplete discovery", "PROJECT_WEEK_MISSING"),
        IncompleteRequirement(task_id, "Incomplete discovery", "REQUIRED_SKILL_MISSING"),
    )
    assert result.requirements == ()


def test_team_requirement_normalizes_skill_label() -> None:
    normalized = TeamRequirement(
        id=UUID("00000000-0000-0000-0000-000000000014"),
        organization_id=ORGANIZATION_ID,
        project_week_id=WEEK_ONE_ID,
        skill_label="  Analysis  ",
        minimum_level=SkillLevel.LEVEL_1,
        required_effort_hours=Decimal("1"),
    )

    assert normalized.skill_label == "analysis"


def test_derivation_canonicalizes_and_deduplicates_task_skill_labels() -> None:
    task_id = UUID("00000000-0000-0000-0000-000000000015")

    result = derive_requirement_draft(
        tasks=(
            task(
                task_id=task_id,
                title="Analyze demand",
                skill_labels=(" Data   Analysis ", "data analysis", "DATA\tANALYSIS"),
                effort=Decimal("8"),
            ),
        )
    )

    assert len(result.requirements) == 1
    assert result.requirements[0].skill_label == "data analysis"
    assert result.requirements[0].required_effort_hours == Decimal("8")
    assert result.requirements[0].task_ids == (task_id,)


def test_blank_task_label_makes_the_whole_task_incomplete_without_partial_aggregation() -> None:
    result = derive_requirement_draft(
        tasks=(
            task(
                title="Unsafe labels",
                skill_labels=("analysis", "   "),
                effort=Decimal("8"),
            ),
        )
    )

    assert result.incomplete_items[0].reason == "REQUIRED_SKILL_MISSING"
    assert result.requirements == ()


@pytest.mark.parametrize(
    ("skill_label", "effort"),
    [("   ", Decimal("1")), ("analysis", Decimal("0")), ("analysis", Decimal("-1"))],
)
def test_team_requirement_rejects_invalid_label_and_nonpositive_effort(
    skill_label: str, effort: Decimal
) -> None:
    with pytest.raises(ValueError):
        TeamRequirement(
            id=UUID("00000000-0000-0000-0000-000000000014"),
            organization_id=ORGANIZATION_ID,
            project_week_id=WEEK_ONE_ID,
            skill_label=skill_label,
            minimum_level=SkillLevel.LEVEL_1,
            required_effort_hours=effort,
        )


def test_derivation_aggregates_same_skill_and_week_with_task_provenance() -> None:
    first_id = UUID("00000000-0000-0000-0000-000000000010")
    second_id = UUID("00000000-0000-0000-0000-000000000011")

    result = derive_requirement_draft(
        tasks=(
            task(
                task_id=second_id,
                title="Write release notes",
                skill_labels=("writing",),
                effort=Decimal("3"),
            ),
            task(
                task_id=first_id,
                title="Research audience",
                skill_labels=("writing",),
                effort=Decimal("5"),
            ),
        )
    )

    requirement = result.requirements[0]
    assert requirement.skill_label == "writing"
    assert requirement.project_week_id == WEEK_ONE_ID
    assert requirement.minimum_level is SkillLevel.LEVEL_1
    assert requirement.required_effort_hours == Decimal("8")
    assert requirement.task_ids == (first_id, second_id)
    assert result.confirmable is True


def test_derivation_keeps_distinct_weeks_and_stably_orders_requirements() -> None:
    result = derive_requirement_draft(
        tasks=(
            task(
                title="Later",
                skill_labels=("zebra",),
                effort=Decimal("2"),
                project_week_id=WEEK_TWO_ID,
            ),
            task(
                title="Earlier",
                skill_labels=("alpha",),
                effort=Decimal("1"),
                project_week_id=WEEK_ONE_ID,
            ),
        )
    )

    assert [(item.project_week_id, item.skill_label) for item in result.requirements] == [
        (WEEK_ONE_ID, "alpha"),
        (WEEK_TWO_ID, "zebra"),
    ]


def test_missing_effort_and_week_remain_explicit_and_never_create_guessed_requirements() -> None:
    no_effort_id = UUID("00000000-0000-0000-0000-000000000012")
    no_week_id = UUID("00000000-0000-0000-0000-000000000013")

    result = derive_requirement_draft(
        tasks=(
            task(
                task_id=no_effort_id,
                title="Estimate me",
                skill_labels=("analysis",),
                effort=None,
            ),
            task(
                task_id=no_week_id,
                title="Schedule me",
                skill_labels=("analysis",),
                effort=Decimal("4"),
                project_week_id=None,
            ),
        )
    )

    assert result.incomplete_items == (
        IncompleteRequirement(no_effort_id, "Estimate me", "ESTIMATED_EFFORT_MISSING"),
        IncompleteRequirement(no_week_id, "Schedule me", "PROJECT_WEEK_MISSING"),
    )
    assert result.requirements == ()
    assert result.confirmable is False
