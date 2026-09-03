"""Immutable capacity and leave values with deterministic range invariants."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class AvailabilityError(Exception):
    """Base class for expected capacity and leave validation failures."""


class InvalidCapacityEntryError(AvailabilityError):
    """A capacity field violates its deterministic boundary."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class InvalidLeaveEntryError(AvailabilityError):
    """A leave field violates its deterministic boundary."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class OverlappingCapacityEntriesError(AvailabilityError):
    """Two capacity entries of the same kind cover the same member and date."""


class CapacityKind(StrEnum):
    """Default capacity or a Project Week-specific override."""

    DEFAULT = "DEFAULT"
    OVERRIDE = "OVERRIDE"


def _hours(value: int, *, field: str, error_type: type[AvailabilityError]) -> int:
    if type(value) is not int or not 0 <= value <= 168:
        raise error_type(field)
    return value


def _capacity_kind(value: CapacityKind | str) -> CapacityKind:
    try:
        return CapacityKind(value)
    except ValueError as error:
        raise InvalidCapacityEntryError("kind") from error


def _capacity_date(value: date, *, field: str) -> date:
    if type(value) is not date:
        raise InvalidCapacityEntryError(field)
    return value


def _leave_date(value: date, *, field: str) -> date:
    if type(value) is not date:
        raise InvalidLeaveEntryError(field)
    return value


def _capacity_range(start: date, end: date) -> tuple[date, date]:
    valid_start = _capacity_date(start, field="effective_from")
    valid_end = _capacity_date(end, field="effective_to")
    if valid_end < valid_start:
        raise InvalidCapacityEntryError("effective_date_range")
    return valid_start, valid_end


def _leave_range(start: date, end: date) -> tuple[date, date]:
    valid_start = _leave_date(start, field="start_date")
    valid_end = _leave_date(end, field="end_date")
    if valid_end < valid_start:
        raise InvalidLeaveEntryError("date_range")
    return valid_start, valid_end


def _capacity_week_start(
    *,
    kind: CapacityKind,
    week_start: date | None,
    project_week_end: date | None,
    effective_from: date,
    effective_to: date,
) -> date | None:
    if kind is CapacityKind.DEFAULT:
        if week_start is not None or project_week_end is not None:
            raise InvalidCapacityEntryError("week_start")
        return None
    if week_start is None:
        raise InvalidCapacityEntryError("week_start")
    valid_week_start = _capacity_date(week_start, field="week_start")
    if valid_week_start != effective_from:
        raise InvalidCapacityEntryError("week_start")
    if project_week_end is None:
        raise InvalidCapacityEntryError("project_week_end")
    valid_week_end = _capacity_date(project_week_end, field="project_week_end")
    if valid_week_end != effective_to:
        raise InvalidCapacityEntryError("effective_date_range")
    return valid_week_start


@dataclass(frozen=True, slots=True)
class CapacityEntryDraft:
    """Validated capacity values before persistence."""

    membership_id: UUID
    kind: CapacityKind
    hours: int
    effective_from: date
    effective_to: date
    week_start: date | None

    @classmethod
    def create(
        cls,
        *,
        membership_id: UUID,
        kind: CapacityKind | str,
        hours: int,
        effective_from: date,
        effective_to: date,
        week_start: date | None,
        project_week_end: date | None = None,
    ) -> CapacityEntryDraft:
        valid_kind = _capacity_kind(kind)
        valid_from, valid_to = _capacity_range(effective_from, effective_to)
        return cls(
            membership_id=membership_id,
            kind=valid_kind,
            hours=_hours(
                hours,
                field="hours",
                error_type=InvalidCapacityEntryError,
            ),
            effective_from=valid_from,
            effective_to=valid_to,
            week_start=_capacity_week_start(
                kind=valid_kind,
                week_start=week_start,
                project_week_end=project_week_end,
                effective_from=valid_from,
                effective_to=valid_to,
            ),
        )


@dataclass(frozen=True, slots=True)
class CapacityEntry:
    """Current version of one tenant-owned capacity entry."""

    id: UUID
    organization_id: UUID
    membership_id: UUID
    kind: CapacityKind
    hours: int
    effective_from: date
    effective_to: date
    week_start: date | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LeaveEntryDraft:
    """Validated inclusive leave range before persistence."""

    membership_id: UUID
    start_date: date
    end_date: date
    unavailable_hours: int

    @classmethod
    def create(
        cls,
        *,
        membership_id: UUID,
        start_date: date,
        end_date: date,
        unavailable_hours: int,
    ) -> LeaveEntryDraft:
        valid_start, valid_end = _leave_range(start_date, end_date)
        return cls(
            membership_id=membership_id,
            start_date=valid_start,
            end_date=valid_end,
            unavailable_hours=_hours(
                unavailable_hours,
                field="unavailable_hours",
                error_type=InvalidLeaveEntryError,
            ),
        )


@dataclass(frozen=True, slots=True)
class LeaveEntry:
    """Current version of one tenant-owned leave entry."""

    id: UUID
    organization_id: UUID
    membership_id: UUID
    start_date: date
    end_date: date
    unavailable_hours: int
    version: int
    created_at: datetime
    updated_at: datetime


CapacityRange = CapacityEntry | CapacityEntryDraft


def ensure_capacity_entry_does_not_overlap(
    candidate: CapacityRange, existing: Iterable[CapacityRange]
) -> None:
    """Reject inclusive overlap for the same member and capacity kind."""

    for entry in existing:
        if entry.membership_id != candidate.membership_id or entry.kind is not candidate.kind:
            continue
        overlaps = (
            candidate.effective_from <= entry.effective_to
            and entry.effective_from <= candidate.effective_to
        )
        if overlaps:
            raise OverlappingCapacityEntriesError
