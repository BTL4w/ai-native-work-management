"""Transactional Project use cases and authorization decisions."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.application.ports import (
    ProjectMutationResult,
    ProjectPage,
    ProjectTransactionFactory,
)
from app.modules.work.domain.projects import (
    Project,
    ProjectDraft,
    ProjectError,
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectPatch,
)

_WRITE_ROLES = frozenset({MembershipRole.ADMIN, MembershipRole.MANAGER})


def _fingerprint(operation: str, values: dict[str, object]) -> str:
    canonical = json.dumps(
        {"operation": operation, "values": values},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class ProjectService:
    """Own Project authorization, validation, and transaction boundaries."""

    def __init__(self, transaction_factory: ProjectTransactionFactory) -> None:
        self._transaction_factory = transaction_factory

    async def list_projects(
        self,
        *,
        actor: AuthenticatedActor,
        query: str | None,
        page: int,
        page_size: int,
    ) -> ProjectPage:
        normalized_query = query.strip() if query is not None else None
        async with self._transaction_factory() as repository:
            return await repository.list_projects(
                actor=actor,
                query=normalized_query or None,
                page=page,
                page_size=page_size,
            )

    async def get_project(self, *, actor: AuthenticatedActor, project_id: UUID) -> Project:
        async with self._transaction_factory() as repository:
            project = await repository.get_project(actor=actor, project_id=project_id)
        if project is None:
            raise ProjectNotFoundError
        return project

    async def _require_writer(
        self, *, actor: AuthenticatedActor, action: str, request_id: str
    ) -> None:
        if actor.role in _WRITE_ROLES:
            return
        async with self._transaction_factory() as repository:
            await repository.audit_rejection(
                actor=actor,
                action=action,
                request_id=request_id,
                reason_code="FORBIDDEN",
            )
        raise ProjectForbiddenError

    async def create_project(
        self,
        *,
        actor: AuthenticatedActor,
        name: str,
        description: str | None,
        request_id: str,
        idempotency_key: str,
    ) -> ProjectMutationResult:
        await self._require_writer(actor=actor, action="project.created", request_id=request_id)
        try:
            draft = ProjectDraft.create(name=name, description=description)
            request_fingerprint = _fingerprint(
                "project.create", {"name": draft.name, "description": draft.description}
            )
            async with self._transaction_factory() as repository:
                return await repository.create_project(
                    actor=actor,
                    draft=draft,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
        except ProjectError as error:
            async with self._transaction_factory() as repository:
                await repository.audit_rejection(
                    actor=actor,
                    action="project.created",
                    request_id=request_id,
                    reason_code=type(error).__name__,
                    idempotency_key=idempotency_key,
                )
            raise

    async def update_project(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        name: str | None,
        name_supplied: bool,
        description: str | None,
        description_supplied: bool,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> ProjectMutationResult:
        await self._require_writer(actor=actor, action="project.updated", request_id=request_id)
        try:
            patch = ProjectPatch.create(
                name=name,
                name_supplied=name_supplied,
                description=description,
                description_supplied=description_supplied,
            )
            patch.validate_not_empty()
            request_fingerprint = _fingerprint(
                "project.update",
                {
                    "project_id": str(project_id),
                    "name": patch.name if patch.name_supplied else {"omitted": True},
                    "description": (
                        patch.description if patch.description_supplied else {"omitted": True}
                    ),
                    "expected_version": expected_version,
                },
            )
            async with self._transaction_factory() as repository:
                return await repository.update_project(
                    actor=actor,
                    project_id=project_id,
                    patch=patch,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
        except ProjectError as error:
            async with self._transaction_factory() as repository:
                await repository.audit_rejection(
                    actor=actor,
                    action="project.updated",
                    request_id=request_id,
                    reason_code=type(error).__name__,
                    idempotency_key=idempotency_key,
                    resource_id=project_id,
                )
            raise
