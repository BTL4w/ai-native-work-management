"""Manager-authorized, versioned Project Team requirement use cases."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.domain.skills import SkillLevel


class TeamRequirementError(Exception):
    """Base expected Team Requirement failure."""


class TeamRequirementForbiddenError(TeamRequirementError):
    pass


class TeamRequirementNotFoundError(TeamRequirementError):
    pass


class TeamRequirementReferenceError(TeamRequirementError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class TeamRequirementIncompleteError(TeamRequirementError):
    pass


class TeamRequirementVersionMismatchError(TeamRequirementError):
    def __init__(self, current_version: int) -> None:
        super().__init__(current_version)
        self.current_version = current_version


class TeamRequirementIdempotencyKeyReusedError(TeamRequirementError):
    pass


class TeamRequirementStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class RequirementItemInput:
    skill_id: UUID
    minimum_level: SkillLevel
    project_week_id: UUID
    effort_hours: int
    source_task_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if not 1 <= int(self.minimum_level) <= 5:
            raise TeamRequirementReferenceError("minimum_level")
        if type(self.effort_hours) is not int or not 0 < self.effort_hours <= 2147483647:
            raise TeamRequirementReferenceError("effort_hours")
        object.__setattr__(self, "source_task_ids", tuple(sorted(set(self.source_task_ids))))


@dataclass(frozen=True, slots=True)
class RequirementItem:
    id: UUID
    skill_id: UUID
    minimum_level: SkillLevel
    project_week_id: UUID
    effort_hours: int
    source_task_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class IncompleteRequirementItem:
    task_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class RequirementSet:
    id: UUID
    organization_id: UUID
    project_id: UUID
    version: int
    status: TeamRequirementStatus
    items: tuple[RequirementItem, ...]
    incomplete_items: tuple[IncompleteRequirementItem, ...]
    created_at: datetime
    updated_at: datetime
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class DeriveRequirementsCommand:
    actor: AuthenticatedActor
    project_id: UUID
    request_id: str
    idempotency_key: str
    # Injection keeps the deterministic Task derivation independently testable;
    # production leaves these None and resolves Task facts inside the repository transaction.
    items: tuple[RequirementItemInput, ...] | None = None
    incomplete_items: tuple[tuple[UUID, str], ...] | None = None


@dataclass(frozen=True, slots=True)
class ReviseRequirementsCommand:
    actor: AuthenticatedActor
    project_id: UUID
    requirement_set_id: UUID
    expected_version: int
    request_id: str
    idempotency_key: str
    items: tuple[RequirementItemInput, ...]
    incomplete_items: tuple[tuple[UUID, str], ...]


@dataclass(frozen=True, slots=True)
class ConfirmRequirementsCommand:
    actor: AuthenticatedActor
    project_id: UUID
    requirement_set_id: UUID
    expected_version: int
    request_id: str
    idempotency_key: str


RequirementCommand = (
    DeriveRequirementsCommand | ReviseRequirementsCommand | ConfirmRequirementsCommand
)
type TaskProvenance = tuple[tuple[UUID, int], ...]


def canonical_task_provenance(values: dict[UUID, int] | TaskProvenance) -> TaskProvenance:
    """Canonicalize a complete Project Task identity/version snapshot."""

    pairs = values.items() if isinstance(values, dict) else values
    versions: dict[UUID, int] = {}
    for task_id, version in pairs:
        if type(version) is not int or version <= 0:
            raise TeamRequirementReferenceError("task_provenance")
        existing = versions.get(task_id)
        if existing is not None and existing != version:
            raise TeamRequirementReferenceError("task_provenance")
        versions[task_id] = version
    return tuple(sorted(versions.items(), key=lambda value: str(value[0])))


def canonical_requirement_command(command: RequirementCommand) -> str:
    """Fingerprint semantically equivalent requirement collections identically."""

    values: dict[str, object] = {
        "kind": type(command).__name__,
        "project_id": str(command.project_id),
    }
    if isinstance(command, (ReviseRequirementsCommand, ConfirmRequirementsCommand)):
        values["requirement_set_id"] = str(command.requirement_set_id)
        values["expected_version"] = command.expected_version
    if isinstance(command, (DeriveRequirementsCommand, ReviseRequirementsCommand)):
        items = command.items or ()
        values["items"] = sorted(
            (
                str(item.skill_id),
                int(item.minimum_level),
                str(item.project_week_id),
                item.effort_hours,
                sorted(str(source_id) for source_id in set(item.source_task_ids)),
            )
            for item in items
        )
        values["incomplete_items"] = sorted(
            (str(task_id), reason) for task_id, reason in (command.incomplete_items or ())
        )
    return sha256(json.dumps(values, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class GetRequirementsQuery:
    actor: AuthenticatedActor
    project_id: UUID


class _Repository(Protocol):
    async def derive(self, command: DeriveRequirementsCommand) -> RequirementSet: ...
    async def revise(self, command: ReviseRequirementsCommand) -> RequirementSet: ...
    async def confirm(self, command: ConfirmRequirementsCommand) -> RequirementSet: ...
    async def get_for_project(
        self, *, actor: AuthenticatedActor, project_id: UUID
    ) -> RequirementSet | None: ...
    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        resource_id: UUID | None,
        reason_code: str,
    ) -> None: ...


class TeamRequirementService:
    def __init__(
        self, transaction_factory: Callable[[], AbstractAsyncContextManager[_Repository]]
    ) -> None:
        self._transactions = transaction_factory

    async def _reject(self, command: RequirementCommand, *, action: str, reason_code: str) -> None:
        async with self._transactions() as repository:
            await repository.audit_rejection(
                actor=command.actor,
                action=action,
                request_id=command.request_id,
                idempotency_key=command.idempotency_key,
                resource_id=getattr(command, "requirement_set_id", None),
                reason_code=reason_code,
            )

    async def audit_transport_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        reason_code: str,
    ) -> None:
        """Persist a rejection raised before a mutation command can be built."""

        async with self._transactions() as repository:
            await repository.audit_rejection(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=None,
                reason_code=reason_code,
            )

    async def derive(self, command: DeriveRequirementsCommand) -> RequirementSet:
        if command.actor.role not in {MembershipRole.ADMIN, MembershipRole.MANAGER}:
            await self._reject(
                command, action="team_requirement.derive.rejected", reason_code="FORBIDDEN"
            )
            raise TeamRequirementForbiddenError
        try:
            async with self._transactions() as repository:
                return await repository.derive(command)
        except TeamRequirementError as error:
            await self._reject(
                command,
                action="team_requirement.derive.rejected",
                reason_code=type(error).__name__,
            )
            raise

    async def revise(self, command: ReviseRequirementsCommand) -> RequirementSet:
        if command.actor.role not in {MembershipRole.ADMIN, MembershipRole.MANAGER}:
            await self._reject(
                command, action="team_requirement.revise.rejected", reason_code="FORBIDDEN"
            )
            raise TeamRequirementForbiddenError
        try:
            keys = [(item.skill_id, item.project_week_id) for item in command.items]
            if len(set(keys)) != len(keys):
                raise TeamRequirementReferenceError("items")
            async with self._transactions() as repository:
                return await repository.revise(command)
        except TeamRequirementError as error:
            await self._reject(
                command,
                action="team_requirement.revise.rejected",
                reason_code=type(error).__name__,
            )
            raise

    async def confirm(self, command: ConfirmRequirementsCommand) -> RequirementSet:
        if command.actor.role not in {MembershipRole.ADMIN, MembershipRole.MANAGER}:
            await self._reject(
                command, action="team_requirement.confirm.rejected", reason_code="FORBIDDEN"
            )
            raise TeamRequirementForbiddenError
        try:
            async with self._transactions() as repository:
                return await repository.confirm(command)
        except TeamRequirementError as error:
            await self._reject(
                command,
                action="team_requirement.confirm.rejected",
                reason_code=type(error).__name__,
            )
            raise

    async def get_for_project(self, query: GetRequirementsQuery) -> RequirementSet:
        async with self._transactions() as repository:
            result = await repository.get_for_project(
                actor=query.actor, project_id=query.project_id
            )
        if result is None:
            raise TeamRequirementNotFoundError
        return result


class InMemoryTeamRequirementRepository:
    """Small deterministic repository used by service/API contract tests."""

    def __init__(
        self,
        *,
        project_managers: set[UUID],
        project_task_versions: dict[UUID, dict[UUID, int]] | None = None,
    ) -> None:
        self.project_managers = project_managers
        self._sets: dict[UUID, RequirementSet] = {}
        self._project_sets: dict[UUID, UUID] = {}
        self._versions: dict[UUID, list[RequirementSet]] = {}
        self._version_provenance: dict[UUID, list[TaskProvenance]] = {}
        self._project_task_versions = {
            project_id: dict(versions)
            for project_id, versions in (project_task_versions or {}).items()
        }
        self._replays: dict[tuple[UUID, str, str], tuple[str, RequirementSet]] = {}
        self.audit_actions: list[str] = []

    async def __aenter__(self) -> InMemoryTeamRequirementRepository:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def version_count(self, set_id: UUID) -> int:
        return len(self._versions[set_id])

    def set_project_task_versions(self, project_id: UUID, versions: dict[UUID, int]) -> None:
        self._project_task_versions[project_id] = dict(versions)

    def _current_task_provenance(
        self,
        *,
        project_id: UUID,
        items: tuple[RequirementItemInput, ...] = (),
        incomplete_items: tuple[tuple[UUID, str], ...] = (),
    ) -> TaskProvenance:
        versions = self._project_task_versions.get(project_id)
        if versions is None:
            task_ids = {task_id for item in items for task_id in item.source_task_ids} | {
                task_id for task_id, _reason in incomplete_items
            }
            versions = {task_id: 1 for task_id in task_ids}
            self._project_task_versions[project_id] = versions
        return canonical_task_provenance(versions)

    def _authorize(self, actor: AuthenticatedActor) -> None:
        if (
            actor.role is not MembershipRole.ADMIN
            and actor.membership_id not in self.project_managers
        ):
            raise TeamRequirementForbiddenError

    @staticmethod
    def _fingerprint(command: RequirementCommand) -> str:
        return canonical_requirement_command(command)

    def _replay(self, command: RequirementCommand, operation: str) -> RequirementSet | None:
        actor = command.actor
        key = command.idempotency_key
        found = self._replays.get((actor.membership_id, operation, key))
        if found is None:
            return None
        if found[0] != self._fingerprint(command):
            raise TeamRequirementIdempotencyKeyReusedError
        return replace(found[1], replayed=True)

    def _save_replay(
        self, command: RequirementCommand, operation: str, value: RequirementSet
    ) -> None:
        actor = command.actor
        key = command.idempotency_key
        self._replays[(actor.membership_id, operation, key)] = (self._fingerprint(command), value)

    @staticmethod
    def _snapshot(
        *,
        set_id: UUID,
        actor: AuthenticatedActor,
        project_id: UUID,
        version: int,
        status: TeamRequirementStatus,
        items: tuple[RequirementItemInput, ...],
        incomplete_items: tuple[tuple[UUID, str], ...],
        now: datetime,
    ) -> RequirementSet:
        return RequirementSet(
            id=set_id,
            organization_id=actor.organization_id,
            project_id=project_id,
            version=version,
            status=status,
            items=tuple(
                RequirementItem(
                    uuid4(),
                    item.skill_id,
                    item.minimum_level,
                    item.project_week_id,
                    item.effort_hours,
                    item.source_task_ids,
                )
                for item in items
            ),
            incomplete_items=tuple(
                IncompleteRequirementItem(task_id, reason) for task_id, reason in incomplete_items
            ),
            created_at=now,
            updated_at=now,
        )

    async def derive(self, command: DeriveRequirementsCommand) -> RequirementSet:
        self._authorize(command.actor)
        replay = self._replay(command, "derive")
        if replay:
            return replay
        if command.project_id in self._project_sets:
            raise TeamRequirementReferenceError("project_id")
        now = datetime.now(UTC)
        set_id = uuid4()
        value = self._snapshot(
            set_id=set_id,
            actor=command.actor,
            project_id=command.project_id,
            version=1,
            status=TeamRequirementStatus.DRAFT,
            items=command.items or (),
            incomplete_items=command.incomplete_items or (),
            now=now,
        )
        self._sets[set_id] = value
        self._project_sets[command.project_id] = set_id
        self._versions[set_id] = [value]
        self._version_provenance[set_id] = [
            self._current_task_provenance(
                project_id=command.project_id,
                items=command.items or (),
                incomplete_items=command.incomplete_items or (),
            )
        ]
        self._save_replay(command, "derive", value)
        self.audit_actions.append("team_requirement.derived")
        return value

    async def revise(self, command: ReviseRequirementsCommand) -> RequirementSet:
        self._authorize(command.actor)
        replay = self._replay(command, "revise")
        if replay:
            return replay
        current = self._sets.get(command.requirement_set_id)
        if current is None or current.project_id != command.project_id:
            raise TeamRequirementNotFoundError
        if current.version != command.expected_version:
            raise TeamRequirementVersionMismatchError(current.version)
        value = self._snapshot(
            set_id=current.id,
            actor=command.actor,
            project_id=current.project_id,
            version=current.version + 1,
            status=TeamRequirementStatus.DRAFT,
            items=command.items,
            incomplete_items=command.incomplete_items,
            now=datetime.now(UTC),
        )
        self._sets[current.id] = value
        self._versions[current.id].append(value)
        self._version_provenance[current.id].append(
            self._current_task_provenance(project_id=current.project_id)
        )
        self._save_replay(command, "revise", value)
        self.audit_actions.append("team_requirement.revised")
        return value

    async def confirm(self, command: ConfirmRequirementsCommand) -> RequirementSet:
        self._authorize(command.actor)
        replay = self._replay(command, "confirm")
        if replay:
            return replay
        current = self._sets.get(command.requirement_set_id)
        if current is None or current.project_id != command.project_id:
            raise TeamRequirementNotFoundError
        if current.version != command.expected_version:
            raise TeamRequirementVersionMismatchError(current.version)
        if current.status is TeamRequirementStatus.STALE:
            raise TeamRequirementIncompleteError
        if current.incomplete_items:
            raise TeamRequirementIncompleteError
        current_provenance = self._current_task_provenance(project_id=current.project_id)
        status = (
            TeamRequirementStatus.CONFIRMED
            if self._version_provenance[current.id][-1] == current_provenance
            else TeamRequirementStatus.STALE
        )
        value = self._snapshot(
            set_id=current.id,
            actor=command.actor,
            project_id=current.project_id,
            version=current.version + 1,
            status=status,
            items=tuple(
                RequirementItemInput(
                    item.skill_id,
                    item.minimum_level,
                    item.project_week_id,
                    item.effort_hours,
                    item.source_task_ids,
                )
                for item in current.items
            ),
            incomplete_items=tuple(
                (item.task_id, item.reason) for item in current.incomplete_items
            ),
            now=datetime.now(UTC),
        )
        self._sets[current.id] = value
        self._versions[current.id].append(value)
        self._version_provenance[current.id].append(current_provenance)
        self._save_replay(command, "confirm", value)
        self.audit_actions.append(
            "team_requirement.confirmed"
            if status is TeamRequirementStatus.CONFIRMED
            else "team_requirement.staled"
        )
        return value

    async def get_for_project(
        self, *, actor: AuthenticatedActor, project_id: UUID
    ) -> RequirementSet | None:
        set_id = self._project_sets.get(project_id)
        return self._sets.get(set_id) if set_id else None

    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        resource_id: UUID | None,
        reason_code: str,
    ) -> None:
        del actor, request_id, idempotency_key, resource_id, reason_code
        self.audit_actions.append(action)
