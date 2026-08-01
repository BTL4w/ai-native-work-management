"""Typed Project persistence ports owned by the work application layer."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.work.domain.projects import Project, ProjectDraft, ProjectPatch


@dataclass(frozen=True, slots=True)
class ProjectPage:
    items: tuple[Project, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ProjectMutationResult:
    project: Project
    replayed: bool


class ProjectRepository(Protocol):
    async def list_projects(
        self, *, actor: AuthenticatedActor, query: str | None, page: int, page_size: int
    ) -> ProjectPage: ...

    async def get_project(
        self, *, actor: AuthenticatedActor, project_id: UUID
    ) -> Project | None: ...

    async def create_project(
        self,
        *,
        actor: AuthenticatedActor,
        draft: ProjectDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ProjectMutationResult: ...

    async def update_project(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        patch: ProjectPatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ProjectMutationResult: ...

    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        reason_code: str,
        idempotency_key: str | None = None,
        resource_id: UUID | None = None,
    ) -> None: ...


ProjectTransactionFactory = Callable[[], AbstractAsyncContextManager[ProjectRepository]]
