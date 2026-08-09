"""Reusable, framework-free Project and Task creation commands."""

from datetime import date
from uuid import UUID

from app.modules.work.domain.projects import ProjectDraft
from app.modules.work.domain.tasks import TaskDraft


def build_project_draft(*, name: str, description: str | None) -> ProjectDraft:
    """Apply the canonical Project creation invariants."""

    return ProjectDraft.create(name=name, description=description)


def build_task_draft(
    *,
    project_id: UUID,
    milestone_id: UUID | None,
    title: str,
    description: str | None,
    assignee_membership_id: UUID,
    due_date: date | None,
) -> TaskDraft:
    """Apply the canonical Task creation invariants."""

    return TaskDraft.create(
        project_id=project_id,
        milestone_id=milestone_id,
        title=title,
        description=description,
        assignee_membership_id=assignee_membership_id,
        due_date=due_date,
    )
