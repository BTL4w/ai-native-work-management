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


@dataclass(frozen=True, slots=True)
class TaskDraft:
    project_id: UUID
    title: str
    description: str | None
    assignee_membership_id: UUID
    due_date: date | None
    initial_status: TaskStatus = TaskStatus.TO_DO

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        title: str,
        description: str | None,
        assignee_membership_id: UUID,
        due_date: date | None,
    ) -> TaskDraft:
        return cls(
            project_id=project_id,
            title=_normalize_title(title),
            description=_normalize_description(description),
            assignee_membership_id=assignee_membership_id,
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
    ) -> TaskPatch:
        effective_title_supplied = title_supplied or title is not None
        if effective_title_supplied and title is None:
            raise InvalidTaskFieldError("title")
        if assignee_supplied and assignee_membership_id is None:
            raise InvalidTaskFieldError("assignee_membership_id")
        return cls(
            title=_normalize_title(title) if title is not None else None,
            title_supplied=effective_title_supplied,
            description=_normalize_description(description) if description_supplied else None,
            description_supplied=description_supplied,
            assignee_membership_id=assignee_membership_id,
            assignee_supplied=assignee_supplied,
            due_date=due_date,
            due_date_supplied=due_date_supplied,
        )

    def validate_not_empty(self) -> None:
        if not any(
            (
                self.title_supplied,
                self.description_supplied,
                self.assignee_supplied,
                self.due_date_supplied,
            )
        ):
            raise EmptyTaskPatchError


@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    organization_id: UUID
    project_id: UUID
    title: str
    description: str | None
    assignee_membership_id: UUID
    assignee_display_name: str
    status: TaskStatus
    due_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime

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
            version=self.version + 1,
            updated_at=updated_at,
        )

    def transition(self, target: TaskStatus, *, updated_at: datetime) -> Task:
        if (self.status, target) not in _ALLOWED_TRANSITIONS:
            raise InvalidStatusTransitionError
        return replace(self, status=target, version=self.version + 1, updated_at=updated_at)
