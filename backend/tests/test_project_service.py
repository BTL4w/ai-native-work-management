"""Project use-case tests using an in-memory persistence port."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.application.ports import ProjectMutationResult, ProjectPage
from app.modules.work.application.project_service import ProjectService
from app.modules.work.domain.projects import (
    Project,
    ProjectDraft,
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectPatch,
    ProjectVersionMismatchError,
)


def _actor(role: MembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="actor@example.test",
        display_name="Actor",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


class FakeProjectTransaction(AbstractAsyncContextManager["FakeProjectTransaction"]):
    def __init__(self, project: Project | None = None) -> None:
        self.project = project
        self.rejections: list[str] = []
        self.created_actor: AuthenticatedActor | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def list_projects(
        self, *, actor: AuthenticatedActor, query: str | None, page: int, page_size: int
    ) -> ProjectPage:
        items = (
            () if actor.role is MembershipRole.EMPLOYEE or self.project is None else (self.project,)
        )
        return ProjectPage(items=items, page=page, page_size=page_size, total=len(items))

    async def get_project(self, *, actor: AuthenticatedActor, project_id: UUID) -> Project | None:
        if actor.role is MembershipRole.EMPLOYEE:
            return None
        if self.project is None or self.project.id != project_id:
            return None
        return self.project

    async def create_project(
        self,
        *,
        actor: AuthenticatedActor,
        draft: ProjectDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ProjectMutationResult:
        self.created_actor = actor
        now = datetime(2026, 8, 1, tzinfo=UTC)
        self.project = Project(
            id=uuid4(),
            organization_id=actor.organization_id,
            name=draft.name,
            description=draft.description,
            version=1,
            created_at=now,
            updated_at=now,
        )
        return ProjectMutationResult(project=self.project, replayed=False)

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
    ) -> ProjectMutationResult:
        if self.project is None or self.project.id != project_id:
            raise ProjectNotFoundError
        if self.project.version != expected_version:
            raise ProjectVersionMismatchError(self.project.version)
        self.project = self.project.apply(patch, updated_at=datetime(2026, 8, 2, tzinfo=UTC))
        return ProjectMutationResult(project=self.project, replayed=False)

    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        reason_code: str,
        idempotency_key: str | None = None,
        resource_id: UUID | None = None,
    ) -> None:
        self.rejections.append(f"{action}:{reason_code}")


@pytest.mark.asyncio
async def test_manager_creates_project_through_transaction_port() -> None:
    transaction = FakeProjectTransaction()
    service = ProjectService(lambda: transaction)
    actor = _actor(MembershipRole.MANAGER)

    result = await service.create_project(
        actor=actor,
        name="  Onboarding  ",
        description=None,
        request_id="request-1",
        idempotency_key="idempotency-key-1",
    )

    assert result.project.name == "Onboarding"
    assert transaction.created_actor == actor


@pytest.mark.asyncio
async def test_employee_project_write_is_rejected_and_audited() -> None:
    transaction = FakeProjectTransaction()
    service = ProjectService(lambda: transaction)

    with pytest.raises(ProjectForbiddenError):
        await service.create_project(
            actor=_actor(MembershipRole.EMPLOYEE),
            name="No access",
            description=None,
            request_id="request-2",
            idempotency_key="idempotency-key-2",
        )

    assert transaction.rejections == ["project.created:FORBIDDEN"]


@pytest.mark.asyncio
async def test_employee_cannot_enumerate_projects_before_assigned_tasks_exist() -> None:
    manager = _actor(MembershipRole.MANAGER)
    project = Project(
        id=uuid4(),
        organization_id=manager.organization_id,
        name="Hidden",
        description=None,
        version=1,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    service = ProjectService(lambda: FakeProjectTransaction(project))

    page = await service.list_projects(
        actor=_actor(MembershipRole.EMPLOYEE), query=None, page=1, page_size=20
    )
    with pytest.raises(ProjectNotFoundError):
        await service.get_project(actor=_actor(MembershipRole.EMPLOYEE), project_id=project.id)

    assert page.items == ()


@pytest.mark.asyncio
async def test_stale_project_update_reports_current_version() -> None:
    actor = _actor(MembershipRole.ADMIN)
    project = Project(
        id=uuid4(),
        organization_id=actor.organization_id,
        name="Current",
        description=None,
        version=4,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    service = ProjectService(lambda: FakeProjectTransaction(project))

    with pytest.raises(ProjectVersionMismatchError) as error:
        await service.update_project(
            actor=actor,
            project_id=project.id,
            name="Stale",
            name_supplied=True,
            description=None,
            description_supplied=False,
            expected_version=3,
            request_id="request-3",
            idempotency_key="idempotency-key-3",
        )

    assert error.value.current_version == 4
