"""Task dependency edge values and local invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID


class DependencyError(Exception):
    """Base class for expected dependency failures."""


class InvalidDependencyError(DependencyError):
    """A dependency edge violates a deterministic invariant."""


@dataclass(frozen=True, slots=True)
class TaskDependencyDraft:
    predecessor_task_id: UUID
    successor_task_id: UUID

    @classmethod
    def create(
        cls,
        *,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
    ) -> TaskDependencyDraft:
        if predecessor_task_id == successor_task_id:
            raise InvalidDependencyError
        return cls(
            predecessor_task_id=predecessor_task_id,
            successor_task_id=successor_task_id,
        )


@dataclass(frozen=True, slots=True)
class TaskDependencyPatch:
    predecessor_task_id: UUID | None = None
    predecessor_supplied: bool = False
    successor_task_id: UUID | None = None
    successor_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        predecessor_task_id: UUID | None = None,
        predecessor_supplied: bool = False,
        successor_task_id: UUID | None = None,
        successor_supplied: bool = False,
    ) -> TaskDependencyPatch:
        effective_predecessor = predecessor_supplied or predecessor_task_id is not None
        effective_successor = successor_supplied or successor_task_id is not None
        if effective_predecessor and predecessor_task_id is None:
            raise InvalidDependencyError
        if effective_successor and successor_task_id is None:
            raise InvalidDependencyError
        if (
            predecessor_task_id is not None
            and successor_task_id is not None
            and predecessor_task_id == successor_task_id
        ):
            raise InvalidDependencyError
        if not effective_predecessor and not effective_successor:
            raise InvalidDependencyError
        return cls(
            predecessor_task_id=predecessor_task_id,
            predecessor_supplied=effective_predecessor,
            successor_task_id=successor_task_id,
            successor_supplied=effective_successor,
        )


@dataclass(frozen=True, slots=True)
class TaskDependency:
    id: UUID
    organization_id: UUID
    predecessor_task_id: UUID
    successor_task_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime

    def apply(self, patch: TaskDependencyPatch, *, updated_at: datetime) -> TaskDependency:
        predecessor = (
            patch.predecessor_task_id
            if patch.predecessor_supplied and patch.predecessor_task_id is not None
            else self.predecessor_task_id
        )
        successor = (
            patch.successor_task_id
            if patch.successor_supplied and patch.successor_task_id is not None
            else self.successor_task_id
        )
        if predecessor == successor:
            raise InvalidDependencyError
        return replace(
            self,
            predecessor_task_id=predecessor,
            successor_task_id=successor,
            version=self.version + 1,
            updated_at=updated_at,
        )
