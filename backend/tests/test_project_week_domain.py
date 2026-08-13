from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.modules.work.planning.domain.project_weeks import (
    CompletedProjectWeekImmutableError,
    InvalidProjectWeekError,
    ProjectWeek,
    ProjectWeekDraft,
    ProjectWeekPatch,
    ProjectWeekStatus,
)


def test_project_week_draft_normalizes_and_validates_range() -> None:
    draft = ProjectWeekDraft.create(
        project_id=uuid4(),
        week_number=1,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
        objective="  Validate the launch plan  ",
        status=ProjectWeekStatus.PLANNED,
    )

    assert draft.objective == "Validate the launch plan"

    with pytest.raises(InvalidProjectWeekError, match="week_number"):
        ProjectWeekDraft.create(
            project_id=uuid4(),
            week_number=0,
            start_date=date(2026, 8, 17),
            end_date=date(2026, 8, 23),
            objective="Invalid",
            status=ProjectWeekStatus.PLANNED,
        )

    with pytest.raises(InvalidProjectWeekError, match="date_range"):
        ProjectWeekDraft.create(
            project_id=uuid4(),
            week_number=1,
            start_date=date(2026, 8, 23),
            end_date=date(2026, 8, 17),
            objective="Invalid",
            status=ProjectWeekStatus.PLANNED,
        )


def test_completed_project_week_is_immutable() -> None:
    now = datetime.now(UTC)
    week = ProjectWeek(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        week_number=1,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 23),
        objective="Delivered baseline",
        status=ProjectWeekStatus.COMPLETED,
        version=2,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(CompletedProjectWeekImmutableError):
        week.apply(
            ProjectWeekPatch.create(objective="Rewrite history", objective_supplied=True),
            updated_at=now,
        )
