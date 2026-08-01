"""Strict public request and response schemas for Projects."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.work.application.ports import ProjectPage
from app.modules.work.domain.projects import Project


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def require_non_blank_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def require_non_blank_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, project: Project) -> Self:
        return cls(
            id=project.id,
            name=project.name,
            description=project.description,
            version=project.version,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectPageResponse(BaseModel):
    items: list[ProjectResponse]
    page: int
    page_size: int
    total: int

    @classmethod
    def from_domain(cls, page: ProjectPage) -> Self:
        return cls(
            items=[ProjectResponse.from_domain(project) for project in page.items],
            page=page.page,
            page_size=page.page_size,
            total=page.total,
        )
