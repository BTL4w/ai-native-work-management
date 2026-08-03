"""Milestone values and deterministic field invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import UUID


class MilestoneError(Exception):
    """Base class for expected Milestone failures."""


class InvalidMilestoneError(MilestoneError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class EmptyMilestonePatchError(MilestoneError):
    """A Milestone patch supplied no mutable field."""


def _name(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise InvalidMilestoneError("name")
    return normalized


def _description(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > 5000:
        raise InvalidMilestoneError("description")
    return normalized or None


def _position(value: int) -> int:
    if value < 1:
        raise InvalidMilestoneError("position")
    return value


@dataclass(frozen=True, slots=True)
class MilestoneDraft:
    project_id: UUID
    name: str
    description: str | None
    target_date: date | None
    position: int

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        name: str,
        description: str | None,
        target_date: date | None,
        position: int,
    ) -> MilestoneDraft:
        return cls(
            project_id=project_id,
            name=_name(name),
            description=_description(description),
            target_date=target_date,
            position=_position(position),
        )


@dataclass(frozen=True, slots=True)
class MilestonePatch:
    name: str | None = None
    name_supplied: bool = False
    description: str | None = None
    description_supplied: bool = False
    target_date: date | None = None
    target_date_supplied: bool = False
    position: int | None = None
    position_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        name: str | None = None,
        name_supplied: bool = False,
        description: str | None = None,
        description_supplied: bool = False,
        target_date: date | None = None,
        target_date_supplied: bool = False,
        position: int | None = None,
        position_supplied: bool = False,
    ) -> MilestonePatch:
        effective_name = name_supplied or name is not None
        effective_position = position_supplied or position is not None
        if effective_name and name is None:
            raise InvalidMilestoneError("name")
        if effective_position and position is None:
            raise InvalidMilestoneError("position")
        return cls(
            name=_name(name) if name is not None else None,
            name_supplied=effective_name,
            description=_description(description) if description_supplied else None,
            description_supplied=description_supplied,
            target_date=target_date,
            target_date_supplied=target_date_supplied,
            position=_position(position) if position is not None else None,
            position_supplied=effective_position,
        )

    def validate_not_empty(self) -> None:
        if not any(
            (
                self.name_supplied,
                self.description_supplied,
                self.target_date_supplied,
                self.position_supplied,
            )
        ):
            raise EmptyMilestonePatchError


@dataclass(frozen=True, slots=True)
class Milestone:
    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    description: str | None
    target_date: date | None
    position: int
    version: int
    created_at: datetime
    updated_at: datetime

    def apply(self, patch: MilestonePatch, *, updated_at: datetime) -> Milestone:
        patch.validate_not_empty()
        return replace(
            self,
            name=patch.name if patch.name_supplied and patch.name is not None else self.name,
            description=patch.description if patch.description_supplied else self.description,
            target_date=patch.target_date if patch.target_date_supplied else self.target_date,
            position=(
                patch.position
                if patch.position_supplied and patch.position is not None
                else self.position
            ),
            version=self.version + 1,
            updated_at=updated_at,
        )
