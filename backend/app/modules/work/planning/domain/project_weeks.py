"""Project Week values and deterministic lifecycle invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class ProjectWeekStatus(StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class ProjectWeekError(Exception):
    """Base class for expected Project Week failures."""


class InvalidProjectWeekError(ProjectWeekError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class EmptyProjectWeekPatchError(ProjectWeekError):
    """A Project Week patch supplied no mutable field."""


class CompletedProjectWeekImmutableError(ProjectWeekError):
    """Completed Project Weeks are historical facts."""


def _week_number(value: int) -> int:
    if value < 1:
        raise InvalidProjectWeekError("week_number")
    return value


def _objective(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 2_000:
        raise InvalidProjectWeekError("objective")
    return normalized


def _range(start_date: date, end_date: date) -> tuple[date, date]:
    if end_date < start_date:
        raise InvalidProjectWeekError("date_range")
    return start_date, end_date


@dataclass(frozen=True, slots=True)
class ProjectWeekDraft:
    project_id: UUID
    week_number: int
    start_date: date
    end_date: date
    objective: str
    status: ProjectWeekStatus = ProjectWeekStatus.PLANNED

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        week_number: int,
        start_date: date,
        end_date: date,
        objective: str,
        status: ProjectWeekStatus = ProjectWeekStatus.PLANNED,
    ) -> ProjectWeekDraft:
        valid_start, valid_end = _range(start_date, end_date)
        return cls(
            project_id=project_id,
            week_number=_week_number(week_number),
            start_date=valid_start,
            end_date=valid_end,
            objective=_objective(objective),
            status=status,
        )


@dataclass(frozen=True, slots=True)
class ProjectWeekPatch:
    week_number: int | None = None
    week_number_supplied: bool = False
    start_date: date | None = None
    start_date_supplied: bool = False
    end_date: date | None = None
    end_date_supplied: bool = False
    objective: str | None = None
    objective_supplied: bool = False
    status: ProjectWeekStatus | None = None
    status_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        week_number: int | None = None,
        week_number_supplied: bool = False,
        start_date: date | None = None,
        start_date_supplied: bool = False,
        end_date: date | None = None,
        end_date_supplied: bool = False,
        objective: str | None = None,
        objective_supplied: bool = False,
        status: ProjectWeekStatus | None = None,
        status_supplied: bool = False,
    ) -> ProjectWeekPatch:
        if week_number_supplied and week_number is None:
            raise InvalidProjectWeekError("week_number")
        if start_date_supplied and start_date is None:
            raise InvalidProjectWeekError("start_date")
        if end_date_supplied and end_date is None:
            raise InvalidProjectWeekError("end_date")
        if objective_supplied and objective is None:
            raise InvalidProjectWeekError("objective")
        if status_supplied and status is None:
            raise InvalidProjectWeekError("status")
        return cls(
            week_number=_week_number(week_number) if week_number is not None else None,
            week_number_supplied=week_number_supplied,
            start_date=start_date,
            start_date_supplied=start_date_supplied,
            end_date=end_date,
            end_date_supplied=end_date_supplied,
            objective=_objective(objective) if objective is not None else None,
            objective_supplied=objective_supplied,
            status=status,
            status_supplied=status_supplied,
        )

    def validate_not_empty(self) -> None:
        if not any(
            (
                self.week_number_supplied,
                self.start_date_supplied,
                self.end_date_supplied,
                self.objective_supplied,
                self.status_supplied,
            )
        ):
            raise EmptyProjectWeekPatchError


@dataclass(frozen=True, slots=True)
class ProjectWeek:
    id: UUID
    organization_id: UUID
    project_id: UUID
    week_number: int
    start_date: date
    end_date: date
    objective: str
    status: ProjectWeekStatus
    version: int
    created_at: datetime
    updated_at: datetime

    def apply(self, patch: ProjectWeekPatch, *, updated_at: datetime) -> ProjectWeek:
        if self.status is ProjectWeekStatus.COMPLETED:
            raise CompletedProjectWeekImmutableError
        patch.validate_not_empty()
        start_date = (
            patch.start_date
            if patch.start_date_supplied and patch.start_date is not None
            else self.start_date
        )
        end_date = (
            patch.end_date
            if patch.end_date_supplied and patch.end_date is not None
            else self.end_date
        )
        valid_start, valid_end = _range(start_date, end_date)
        return replace(
            self,
            week_number=(
                patch.week_number
                if patch.week_number_supplied and patch.week_number is not None
                else self.week_number
            ),
            start_date=valid_start,
            end_date=valid_end,
            objective=(
                patch.objective
                if patch.objective_supplied and patch.objective is not None
                else self.objective
            ),
            status=(
                patch.status if patch.status_supplied and patch.status is not None else self.status
            ),
            version=self.version + 1,
            updated_at=updated_at,
        )
