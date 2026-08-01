"""Project values, invariants, and explicit application-facing failures."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID


class ProjectError(Exception):
    """Base class for expected Project failures."""


class InvalidProjectFieldError(ProjectError):
    """A Project field violates its deterministic boundary."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class EmptyProjectPatchError(ProjectError):
    """A Project update supplied no mutable field."""


class ProjectForbiddenError(ProjectError):
    """The authenticated actor cannot perform the requested Project mutation."""


class ProjectNotFoundError(ProjectError):
    """The Project does not exist or is not visible to the actor."""


class ProjectVersionMismatchError(ProjectError):
    """A stale mutation attempted to overwrite a newer Project version."""

    def __init__(self, current_version: int) -> None:
        super().__init__(current_version)
        self.current_version = current_version


class IdempotencyKeyReusedError(ProjectError):
    """An idempotency key was reused for a different normalized request."""


def _normalize_name(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 160:
        raise InvalidProjectFieldError("name")
    return normalized


def _normalize_description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > 5000:
        raise InvalidProjectFieldError("description")
    return normalized or None


@dataclass(frozen=True, slots=True)
class ProjectDraft:
    """Validated inputs for a new Project."""

    name: str
    description: str | None

    @classmethod
    def create(cls, *, name: str, description: str | None) -> ProjectDraft:
        return cls(name=_normalize_name(name), description=_normalize_description(description))


@dataclass(frozen=True, slots=True)
class ProjectPatch:
    """Validated partial Project changes while preserving omitted/null semantics."""

    name: str | None = None
    name_supplied: bool = False
    description: str | None = None
    description_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        name: str | None = None,
        name_supplied: bool = False,
        description: str | None = None,
        description_supplied: bool = False,
    ) -> ProjectPatch:
        effective_name_supplied = name_supplied or name is not None
        normalized_name = (
            _normalize_name(name) if effective_name_supplied and name is not None else None
        )
        if effective_name_supplied and name is None:
            raise InvalidProjectFieldError("name")
        normalized_description = (
            _normalize_description(description) if description_supplied else None
        )
        return cls(
            name=normalized_name,
            name_supplied=effective_name_supplied,
            description=normalized_description,
            description_supplied=description_supplied,
        )

    def validate_not_empty(self) -> None:
        if not self.name_supplied and not self.description_supplied:
            raise EmptyProjectPatchError


@dataclass(frozen=True, slots=True)
class Project:
    """Tenant-owned Project business resource."""

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    version: int
    created_at: datetime
    updated_at: datetime

    def apply(self, patch: ProjectPatch, *, updated_at: datetime) -> Project:
        patch.validate_not_empty()
        return replace(
            self,
            name=patch.name if patch.name_supplied else self.name,
            description=patch.description if patch.description_supplied else self.description,
            version=self.version + 1,
            updated_at=updated_at,
        )
