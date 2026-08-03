"""Strict public Task request and response schemas."""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.work.application.task_ports import TaskPage
from app.modules.work.domain.tasks import Task, TaskStatus


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    milestone_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    assignee_membership_id: UUID
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("title must not be blank")
        return normalized


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    assignee_membership_id: UUID | None = None
    due_date: date | None = None
    milestone_id: UUID | None = None


class TaskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_status: TaskStatus


class AssigneeResponse(BaseModel):
    membership_id: UUID
    display_name: str


class TaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    milestone_id: UUID | None
    title: str
    description: str | None
    assignee: AssigneeResponse
    status: TaskStatus
    due_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, task: Task) -> Self:
        return cls(
            id=task.id,
            project_id=task.project_id,
            milestone_id=task.milestone_id,
            title=task.title,
            description=task.description,
            assignee=AssigneeResponse(
                membership_id=task.assignee_membership_id, display_name=task.assignee_display_name
            ),
            status=task.status,
            due_date=task.due_date,
            version=task.version,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class TaskPageResponse(BaseModel):
    items: list[TaskResponse]
    page: int
    page_size: int
    total: int

    @classmethod
    def from_domain(cls, result: TaskPage) -> Self:
        return cls(
            items=[TaskResponse.from_domain(task) for task in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        )
