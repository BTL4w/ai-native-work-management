"""Strict request and response schemas for manual planning resources."""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.work.planning.application.manual_ports import PlanningDeleteResult, PlanningPage
from app.modules.work.planning.domain.acceptance_criteria import AcceptanceCriterion
from app.modules.work.planning.domain.dependencies import TaskDependency
from app.modules.work.planning.domain.goals import Goal
from app.modules.work.planning.domain.milestones import Milestone


class GoalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    expected_outcomes: list[str] = Field(default_factory=list)
    target_date: date | None = None


class GoalUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    expected_outcomes: list[str] | None = None
    target_date: date | None = None


class MilestoneCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    target_date: date | None = None
    position: int = Field(ge=1)


class MilestoneUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    target_date: date | None = None
    position: int | None = Field(default=None, ge=1)


class DependencyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predecessor_task_id: UUID
    successor_task_id: UUID


class DependencyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predecessor_task_id: UUID | None = None
    successor_task_id: UUID | None = None


class AcceptanceCriterionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    position: int = Field(ge=1)


class AcceptanceCriterionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    position: int | None = Field(default=None, ge=1)


class GoalResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str | None
    expected_outcomes: list[str]
    target_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, item: Goal) -> Self:
        return cls(
            id=item.id,
            project_id=item.project_id,
            title=item.title,
            description=item.description,
            expected_outcomes=list(item.expected_outcomes),
            target_date=item.target_date,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class MilestoneResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str | None
    target_date: date | None
    position: int
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, item: Milestone) -> Self:
        return cls(
            id=item.id,
            project_id=item.project_id,
            name=item.name,
            description=item.description,
            target_date=item.target_date,
            position=item.position,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class DependencyResponse(BaseModel):
    id: UUID
    predecessor_task_id: UUID
    successor_task_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, item: TaskDependency) -> Self:
        return cls(
            id=item.id,
            predecessor_task_id=item.predecessor_task_id,
            successor_task_id=item.successor_task_id,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class AcceptanceCriterionResponse(BaseModel):
    id: UUID
    task_id: UUID
    text: str
    position: int
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, item: AcceptanceCriterion) -> Self:
        return cls(
            id=item.id,
            task_id=item.task_id,
            text=item.text,
            position=item.position,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class PlanningPageResponse(BaseModel):
    items: list[GoalResponse | MilestoneResponse | DependencyResponse | AcceptanceCriterionResponse]
    page: int
    page_size: int
    total: int

    @classmethod
    def goals(cls, page: PlanningPage) -> Self:
        return cls(
            items=[GoalResponse.from_domain(item) for item in page.items if isinstance(item, Goal)],
            page=page.page,
            page_size=page.page_size,
            total=page.total,
        )

    @classmethod
    def milestones(cls, page: PlanningPage) -> Self:
        return cls(
            items=[
                MilestoneResponse.from_domain(item)
                for item in page.items
                if isinstance(item, Milestone)
            ],
            page=page.page,
            page_size=page.page_size,
            total=page.total,
        )

    @classmethod
    def dependencies(cls, page: PlanningPage) -> Self:
        return cls(
            items=[
                DependencyResponse.from_domain(item)
                for item in page.items
                if isinstance(item, TaskDependency)
            ],
            page=page.page,
            page_size=page.page_size,
            total=page.total,
        )

    @classmethod
    def criteria(cls, page: PlanningPage) -> Self:
        return cls(
            items=[
                AcceptanceCriterionResponse.from_domain(item)
                for item in page.items
                if isinstance(item, AcceptanceCriterion)
            ],
            page=page.page,
            page_size=page.page_size,
            total=page.total,
        )


class DeleteResponse(BaseModel):
    id: UUID
    version: int

    @classmethod
    def from_domain(cls, result: PlanningDeleteResult) -> Self:
        return cls(id=result.resource_id, version=result.version)
