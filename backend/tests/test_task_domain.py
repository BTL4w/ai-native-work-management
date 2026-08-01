"""Framework-independent Task invariant tests."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.modules.work.domain.tasks import (
    EmptyTaskPatchError,
    InvalidStatusTransitionError,
    InvalidTaskFieldError,
    Task,
    TaskDraft,
    TaskPatch,
    TaskStatus,
)


def _task(status: TaskStatus = TaskStatus.TO_DO) -> Task:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    return Task(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        title="Collect documents",
        description="Checklist",
        assignee_membership_id=uuid4(),
        assignee_display_name="Employee",
        status=status,
        due_date=date(2026, 8, 12),
        version=1,
        created_at=now,
        updated_at=now,
    )


def test_task_draft_normalizes_text_and_always_starts_to_do() -> None:
    draft = TaskDraft.create(
        project_id=uuid4(),
        title="  Collect documents  ",
        description="  Checklist  ",
        assignee_membership_id=uuid4(),
        due_date=date(2026, 8, 12),
    )

    assert draft.title == "Collect documents"
    assert draft.description == "Checklist"
    assert draft.initial_status is TaskStatus.TO_DO


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_task_draft_rejects_invalid_title(title: str) -> None:
    with pytest.raises(InvalidTaskFieldError) as error:
        TaskDraft.create(
            project_id=uuid4(),
            title=title,
            description=None,
            assignee_membership_id=uuid4(),
            due_date=None,
        )
    assert error.value.field == "title"


def test_task_patch_preserves_omitted_and_explicit_null_fields() -> None:
    with pytest.raises(EmptyTaskPatchError):
        TaskPatch.create().validate_not_empty()

    patch = TaskPatch.create(
        description=None, description_supplied=True, due_date=None, due_date_supplied=True
    )
    updated = _task().apply(patch, updated_at=datetime(2026, 8, 2, tzinfo=UTC))

    assert updated.description is None
    assert updated.due_date is None
    assert updated.version == 2


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.TO_DO, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.TO_DO),
        (TaskStatus.IN_PROGRESS, TaskStatus.DONE),
        (TaskStatus.DONE, TaskStatus.IN_PROGRESS),
    ],
)
def test_task_accepts_only_documented_status_edges(current: TaskStatus, target: TaskStatus) -> None:
    transitioned = _task(current).transition(target, updated_at=datetime(2026, 8, 2, tzinfo=UTC))
    assert transitioned.status is target
    assert transitioned.version == 2


def test_task_rejects_to_do_directly_to_done() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        _task().transition(TaskStatus.DONE, updated_at=datetime(2026, 8, 2, tzinfo=UTC))
