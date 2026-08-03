"""Planning domain normalization and invariant tests."""

from datetime import date
from uuid import uuid4

import pytest

from app.modules.work.planning.domain.acceptance_criteria import (
    AcceptanceCriterionDraft,
    AcceptanceCriterionPatch,
    InvalidAcceptanceCriterionError,
)
from app.modules.work.planning.domain.dependencies import (
    InvalidDependencyError,
    TaskDependencyDraft,
)
from app.modules.work.planning.domain.goals import GoalDraft, GoalPatch, InvalidGoalError
from app.modules.work.planning.domain.milestones import (
    InvalidMilestoneError,
    MilestoneDraft,
    MilestonePatch,
)


def test_dependency_rejects_self_edge() -> None:
    task_id = uuid4()

    with pytest.raises(InvalidDependencyError):
        TaskDependencyDraft.create(
            predecessor_task_id=task_id,
            successor_task_id=task_id,
        )


def test_acceptance_criterion_normalizes_required_text() -> None:
    draft = AcceptanceCriterionDraft.create(
        task_id=uuid4(),
        text="  Customs form accepted  ",
        position=1,
    )

    assert draft.text == "Customs form accepted"


@pytest.mark.parametrize("text", ["", "   "])
def test_acceptance_criterion_rejects_blank_text(text: str) -> None:
    with pytest.raises(InvalidAcceptanceCriterionError):
        AcceptanceCriterionDraft.create(task_id=uuid4(), text=text, position=1)


def test_goal_normalizes_fields_and_expected_outcomes() -> None:
    draft = GoalDraft.create(
        project_id=uuid4(),
        title="  Expand supplier network  ",
        description="  Add qualified regional suppliers  ",
        expected_outcomes=("  Ten suppliers qualified  ", "", "Faster sourcing"),
        target_date=date(2026, 12, 31),
    )

    assert draft.title == "Expand supplier network"
    assert draft.description == "Add qualified regional suppliers"
    assert draft.expected_outcomes == ("Ten suppliers qualified", "Faster sourcing")


def test_goal_rejects_duplicate_normalized_expected_outcomes() -> None:
    with pytest.raises(InvalidGoalError):
        GoalDraft.create(
            project_id=uuid4(),
            title="Supplier readiness",
            description=None,
            expected_outcomes=("Approved list", "  Approved list  "),
            target_date=None,
        )


@pytest.mark.parametrize("position", [0, -1])
def test_display_positions_must_be_positive(position: int) -> None:
    with pytest.raises(InvalidMilestoneError):
        MilestoneDraft.create(
            project_id=uuid4(),
            name="Qualification",
            description=None,
            target_date=None,
            position=position,
        )
    with pytest.raises(InvalidAcceptanceCriterionError):
        AcceptanceCriterionDraft.create(
            task_id=uuid4(),
            text="Approved",
            position=position,
        )


def test_nullable_patch_fields_distinguish_omitted_from_clear() -> None:
    goal_patch = GoalPatch.create(description=None, description_supplied=True)
    milestone_patch = MilestonePatch.create(target_date=None, target_date_supplied=True)
    criterion_patch = AcceptanceCriterionPatch.create(text="  Signed off  ")

    assert goal_patch.description_supplied is True
    assert goal_patch.description is None
    assert milestone_patch.target_date_supplied is True
    assert milestone_patch.target_date is None
    assert criterion_patch.text_supplied is True
    assert criterion_patch.text == "Signed off"
