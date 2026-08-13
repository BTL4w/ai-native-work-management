"""Task values, deterministic workflow, and explicit failures."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class TaskStatus(StrEnum):
    TO_DO = "TO_DO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class TaskError(Exception):
    """Base class for expected Task failures."""


class InvalidTaskFieldError(TaskError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class EmptyTaskPatchError(TaskError):
    """A Task update supplied no mutable fields."""


class TaskForbiddenError(TaskError):
    """The actor may not perform the requested Task action."""


class TaskNotFoundError(TaskError):
    """The Task is absent or invisible to the actor."""


class TaskVersionMismatchError(TaskError):
    def __init__(self, current_version: int) -> None:
        super().__init__(current_version)
        self.current_version = current_version


class InvalidStatusTransitionError(TaskError):
    """The requested status edge is outside the fixed Phase 1 workflow."""


class TaskReferenceError(TaskError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class TaskIdempotencyKeyReusedError(TaskError):
    """A Task idempotency key was reused for another normalized request."""


_ALLOWED_TRANSITIONS = frozenset(
    {
        (TaskStatus.TO_DO, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.TO_DO),
        (TaskStatus.IN_PROGRESS, TaskStatus.DONE),
        (TaskStatus.DONE, TaskStatus.IN_PROGRESS),
    }
)


def _normalize_title(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise InvalidTaskFieldError("title")
    return normalized


def _normalize_description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > 10_000:
        raise InvalidTaskFieldError("description")
    return normalized or None


def _normalize_skill_labels(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(value.strip().lower() for value in values if value.strip()))
    if len(normalized) > 20 or any(len(value) > 80 for value in normalized):
        raise InvalidTaskFieldError("required_skill_labels")
    return normalized


def _estimated_effort(value: int) -> int:
    if not 1 <= value <= 10_000:
        raise InvalidTaskFieldError("estimated_effort_hours")
    return value


@dataclass(frozen=True, slots=True)
class TaskDraft:
    project_id: UUID
    project_week_id: UUID
    milestone_id: UUID | None
    title: str
    description: str | None
    assignee_membership_id: UUID | None
    required_skill_labels: tuple[str, ...]
    estimated_effort_hours: int
    due_date: date | None
    initial_status: TaskStatus = TaskStatus.TO_DO

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        project_week_id: UUID | None,
        milestone_id: UUID | None,
        title: str,
        description: str | None,
        assignee_membership_id: UUID | None,
        required_skill_labels: tuple[str, ...],
        estimated_effort_hours: int,
        due_date: date | None,
    ) -> TaskDraft:
        if project_week_id is None:
            raise InvalidTaskFieldError("project_week_id")
        return cls(
            project_id=project_id,
            project_week_id=project_week_id,
            milestone_id=milestone_id,
            title=_normalize_title(title),
            description=_normalize_description(description),
            assignee_membership_id=assignee_membership_id,
            required_skill_labels=_normalize_skill_labels(required_skill_labels),
            estimated_effort_hours=_estimated_effort(estimated_effort_hours),
            due_date=due_date,
        )


@dataclass(frozen=True, slots=True)
class TaskPatch:
    title: str | None = None
    title_supplied: bool = False
    description: str | None = None
    description_supplied: bool = False
    assignee_membership_id: UUID | None = None
    assignee_supplied: bool = False
    due_date: date | None = None
    due_date_supplied: bool = False
    milestone_id: UUID | None = None
    milestone_supplied: bool = False
    project_week_id: UUID | None = None
    project_week_supplied: bool = False
    required_skill_labels: tuple[str, ...] = ()
    required_skill_labels_supplied: bool = False
    estimated_effort_hours: int | None = None
    estimated_effort_hours_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        title: str | None = None,
        title_supplied: bool = False,
        description: str | None = None,
        description_supplied: bool = False,
        assignee_membership_id: UUID | None = None,
        assignee_supplied: bool = False,
        due_date: date | None = None,
        due_date_supplied: bool = False,
        milestone_id: UUID | None = None,
        milestone_supplied: bool = False,
        project_week_id: UUID | None = None,
        project_week_supplied: bool = False,
        required_skill_labels: tuple[str, ...] = (),
        required_skill_labels_supplied: bool = False,
        estimated_effort_hours: int | None = None,
        estimated_effort_hours_supplied: bool = False,
    ) -> TaskPatch:
        effective_title_supplied = title_supplied or title is not None
        if effective_title_supplied and title is None:
            raise InvalidTaskFieldError("title")
        if assignee_supplied and assignee_membership_id is None:
            raise InvalidTaskFieldError("assignee_membership_id")
        if project_week_supplied and project_week_id is None:
            raise InvalidTaskFieldError("project_week_id")
        if estimated_effort_hours_supplied and estimated_effort_hours is None:
            raise InvalidTaskFieldError("estimated_effort_hours")
        return cls(
            title=_normalize_title(title) if title is not None else None,
            title_supplied=effective_title_supplied,
            description=_normalize_description(description) if description_supplied else None,
            description_supplied=description_supplied,
            assignee_membership_id=assignee_membership_id,
            assignee_supplied=assignee_supplied,
            due_date=due_date,
            due_date_supplied=due_date_supplied,
            milestone_id=milestone_id,
            milestone_supplied=milestone_supplied,
            project_week_id=project_week_id,
            project_week_supplied=project_week_supplied,
            required_skill_labels=(
                _normalize_skill_labels(required_skill_labels)
                if required_skill_labels_supplied
                else ()
            ),
            required_skill_labels_supplied=required_skill_labels_supplied,
            estimated_effort_hours=(
                _estimated_effort(estimated_effort_hours)
                if estimated_effort_hours is not None
                else None
            ),
            estimated_effort_hours_supplied=estimated_effort_hours_supplied,
        )

    def validate_not_empty(self) -> None:
        if not any(
            (
                self.title_supplied,
                self.description_supplied,
                self.assignee_supplied,
                self.due_date_supplied,
                self.milestone_supplied,
                self.project_week_supplied,
                self.required_skill_labels_supplied,
                self.estimated_effort_hours_supplied,
            )
        ):
            raise EmptyTaskPatchError


@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    organization_id: UUID
    project_id: UUID
    milestone_id: UUID | None
    title: str
    description: str | None
    assignee_membership_id: UUID | None
    assignee_display_name: str | None
    status: TaskStatus
    due_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime
    project_week_id: UUID | None = None
    required_skill_labels: tuple[str, ...] = ()
    estimated_effort_hours: int | None = None

    def apply(self, patch: TaskPatch, *, updated_at: datetime) -> Task:
        patch.validate_not_empty()
        return replace(
            self,
            title=patch.title if patch.title_supplied else self.title,
            description=patch.description if patch.description_supplied else self.description,
            assignee_membership_id=(
                patch.assignee_membership_id
                if patch.assignee_supplied and patch.assignee_membership_id is not None
                else self.assignee_membership_id
            ),
            due_date=patch.due_date if patch.due_date_supplied else self.due_date,
            milestone_id=patch.milestone_id if patch.milestone_supplied else self.milestone_id,
            project_week_id=(
                patch.project_week_id if patch.project_week_supplied else self.project_week_id
            ),
            required_skill_labels=(
                patch.required_skill_labels
                if patch.required_skill_labels_supplied
                else self.required_skill_labels
            ),
            estimated_effort_hours=(
                patch.estimated_effort_hours
                if patch.estimated_effort_hours_supplied
                else self.estimated_effort_hours
            ),
            version=self.version + 1,
            updated_at=updated_at,
        )

    def transition(self, target: TaskStatus, *, updated_at: datetime) -> Task:
        if (self.status, target) not in _ALLOWED_TRANSITIONS:
            raise InvalidStatusTransitionError
        return replace(self, status=target, version=self.version + 1, updated_at=updated_at)
