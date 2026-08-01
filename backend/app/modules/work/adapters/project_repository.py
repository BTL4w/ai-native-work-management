"""SQLAlchemy Project persistence, audit, tenant context, and idempotency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.adapters.database_models import AuditEventModel
from app.modules.audit.domain.events import AuditOutcome
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.adapters.database_models import (
    IdempotencyRecordModel,
    IdempotencyState,
    ProjectModel,
    TaskModel,
)
from app.modules.work.application.ports import (
    ProjectMutationResult,
    ProjectPage,
    ProjectRepository,
)
from app.modules.work.domain.projects import (
    IdempotencyKeyReusedError,
    Project,
    ProjectDraft,
    ProjectNotFoundError,
    ProjectPatch,
    ProjectVersionMismatchError,
)

_IDEMPOTENCY_TTL = timedelta(hours=24)


def _to_domain(model: ProjectModel) -> Project:
    return Project(
        id=model.id,
        organization_id=model.organization_id,
        name=model.name,
        description=model.description,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_json(project: Project) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "organization_id": str(project.organization_id),
        "name": project.name,
        "description": project.description,
        "version": project.version,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def _from_json(value: dict[str, Any]) -> Project:
    return Project(
        id=UUID(str(value["id"])),
        organization_id=UUID(str(value["organization_id"])),
        name=str(value["name"]),
        description=str(value["description"]) if value["description"] is not None else None,
        version=int(value["version"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
    )


class SqlAlchemyProjectRepository:
    """Implement Project operations inside one transaction-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _activate_actor(self, actor: AuthenticatedActor) -> None:
        await self._session.execute(text("SET LOCAL ROLE app_runtime"))
        await self._session.execute(
            text("SELECT set_config('app.organization_id', :value, true)"),
            {"value": str(actor.organization_id)},
        )
        await self._session.execute(
            text("SELECT set_config('app.membership_id', :value, true)"),
            {"value": str(actor.membership_id)},
        )

    async def list_projects(
        self, *, actor: AuthenticatedActor, query: str | None, page: int, page_size: int
    ) -> ProjectPage:
        await self._activate_actor(actor)
        predicates = [ProjectModel.organization_id == actor.organization_id]
        if actor.role is MembershipRole.EMPLOYEE:
            predicates.append(
                select(TaskModel.id)
                .where(
                    TaskModel.organization_id == ProjectModel.organization_id,
                    TaskModel.project_id == ProjectModel.id,
                    TaskModel.assignee_membership_id == actor.membership_id,
                )
                .exists()
            )
        if query is not None:
            pattern = f"%{query}%"
            predicates.append(
                or_(ProjectModel.name.ilike(pattern), ProjectModel.description.ilike(pattern))
            )
        total = await self._session.scalar(
            select(func.count()).select_from(ProjectModel).where(*predicates)
        )
        models = await self._session.scalars(
            select(ProjectModel)
            .where(*predicates)
            .order_by(ProjectModel.created_at.desc(), ProjectModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return ProjectPage(
            items=tuple(_to_domain(model) for model in models),
            page=page,
            page_size=page_size,
            total=total or 0,
        )

    async def get_project(self, *, actor: AuthenticatedActor, project_id: UUID) -> Project | None:
        await self._activate_actor(actor)
        predicates = [
            ProjectModel.organization_id == actor.organization_id,
            ProjectModel.id == project_id,
        ]
        if actor.role is MembershipRole.EMPLOYEE:
            predicates.append(
                select(TaskModel.id)
                .where(
                    TaskModel.organization_id == ProjectModel.organization_id,
                    TaskModel.project_id == ProjectModel.id,
                    TaskModel.assignee_membership_id == actor.membership_id,
                )
                .exists()
            )
        model = await self._session.scalar(select(ProjectModel).where(*predicates))
        return _to_domain(model) if model is not None else None

    async def _find_replay(
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ProjectMutationResult | None:
        record = await self._session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.organization_id == actor.organization_id,
                IdempotencyRecordModel.actor_membership_id == actor.membership_id,
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.idempotency_key == idempotency_key,
            )
        )
        if record is None:
            return None
        if record.request_fingerprint != request_fingerprint:
            raise IdempotencyKeyReusedError
        if record.state is not IdempotencyState.COMPLETED or record.response_body is None:
            raise IdempotencyKeyReusedError
        return ProjectMutationResult(project=_from_json(record.response_body), replayed=True)

    def _new_idempotency(
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> IdempotencyRecordModel:
        record = IdempotencyRecordModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            actor_membership_id=actor.membership_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            state=IdempotencyState.IN_PROGRESS,
            response_status=None,
            response_body=None,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        self._session.add(record)
        return record

    def _audit_success(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        project: Project,
        request_id: str,
        idempotency_key: str,
        before_data: dict[str, object],
        after_data: dict[str, object],
    ) -> None:
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=AuditOutcome.SUCCEEDED,
                resource_type="project",
                resource_id=project.id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data=before_data,
                after_data=after_data,
                reason_data={},
            )
        )

    async def create_project(
        self,
        *,
        actor: AuthenticatedActor,
        draft: ProjectDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ProjectMutationResult:
        await self._activate_actor(actor)
        operation = "project.create"
        replay = await self._find_replay(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return replay

        now = datetime.now(UTC)
        record = self._new_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            now=now,
        )
        model = ProjectModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            name=draft.name,
            description=draft.description,
            version=1,
            created_by_membership_id=actor.membership_id,
            updated_by_membership_id=actor.membership_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        await self._session.flush()
        project = _to_domain(model)
        self._audit_success(
            actor=actor,
            action="project.created",
            project=project,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data={},
            after_data={"name": project.name, "description": project.description},
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201
        record.response_body = _to_json(project)
        return ProjectMutationResult(project=project, replayed=False)

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
        await self._activate_actor(actor)
        operation = f"project.update:{project_id}"
        replay = await self._find_replay(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if replay is not None:
            return replay

        model = await self._session.scalar(
            select(ProjectModel)
            .where(
                ProjectModel.organization_id == actor.organization_id,
                ProjectModel.id == project_id,
            )
            .with_for_update()
        )
        if model is None:
            raise ProjectNotFoundError
        if model.version != expected_version:
            raise ProjectVersionMismatchError(model.version)

        now = datetime.now(UTC)
        record = self._new_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            now=now,
        )
        before_data: dict[str, object] = {}
        after_data: dict[str, object] = {}
        if patch.name_supplied:
            before_data["name"] = model.name
            model.name = patch.name or ""
            after_data["name"] = model.name
        if patch.description_supplied:
            before_data["description"] = model.description
            model.description = patch.description
            after_data["description"] = model.description
        model.version += 1
        model.updated_at = now
        model.updated_by_membership_id = actor.membership_id
        await self._session.flush()
        project = _to_domain(model)
        self._audit_success(
            actor=actor,
            action="project.updated",
            project=project,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data=before_data,
            after_data=after_data,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = _to_json(project)
        return ProjectMutationResult(project=project, replayed=False)

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
        await self._activate_actor(actor)
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=AuditOutcome.REJECTED,
                resource_type="project",
                resource_id=resource_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data={},
                after_data={},
                reason_data={"code": reason_code},
            )
        )


class SqlAlchemyProjectTransactionFactory:
    """Create one commit-or-rollback session for each Project service operation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[ProjectRepository]:
        async with self._session_factory.begin() as session:
            yield SqlAlchemyProjectRepository(session)
