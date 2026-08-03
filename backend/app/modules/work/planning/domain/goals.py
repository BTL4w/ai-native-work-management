"""Goal values, normalization, and resource-version behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import UUID


class GoalError(Exception):
    """Base class for expected Goal failures."""


class InvalidGoalError(GoalError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class EmptyGoalPatchError(GoalError):
    """A Goal patch supplied no mutable field."""


def _required(value: str, *, field: str, limit: int) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= limit:
        raise InvalidGoalError(field)
    return normalized


def _optional(value: str | None, *, field: str, limit: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > limit:
        raise InvalidGoalError(field)
    return normalized or None


def _outcomes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values if value.strip())
    if any(len(value) > 500 for value in normalized):
        raise InvalidGoalError("expected_outcomes")
    if len(set(normalized)) != len(normalized):
        raise InvalidGoalError("expected_outcomes")
    return normalized


@dataclass(frozen=True, slots=True)
class GoalDraft:
    project_id: UUID
    title: str
    description: str | None
    expected_outcomes: tuple[str, ...]
    target_date: date | None

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        title: str,
        description: str | None,
        expected_outcomes: tuple[str, ...],
        target_date: date | None,
    ) -> GoalDraft:
        return cls(
            project_id=project_id,
            title=_required(title, field="title", limit=200),
            description=_optional(description, field="description", limit=5000),
            expected_outcomes=_outcomes(expected_outcomes),
            target_date=target_date,
        )


@dataclass(frozen=True, slots=True)
class GoalPatch:
    title: str | None = None
    title_supplied: bool = False
    description: str | None = None
    description_supplied: bool = False
    expected_outcomes: tuple[str, ...] = ()
    expected_outcomes_supplied: bool = False
    target_date: date | None = None
    target_date_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        title: str | None = None,
        title_supplied: bool = False,
        description: str | None = None,
        description_supplied: bool = False,
        expected_outcomes: tuple[str, ...] = (),
        expected_outcomes_supplied: bool = False,
        target_date: date | None = None,
        target_date_supplied: bool = False,
    ) -> GoalPatch:
        effective_title = title_supplied or title is not None
        if effective_title and title is None:
            raise InvalidGoalError("title")
        return cls(
            title=_required(title, field="title", limit=200) if title is not None else None,
            title_supplied=effective_title,
            description=(
                _optional(description, field="description", limit=5000)
                if description_supplied
                else None
            ),
            description_supplied=description_supplied,
            expected_outcomes=_outcomes(expected_outcomes) if expected_outcomes_supplied else (),
            expected_outcomes_supplied=expected_outcomes_supplied,
            target_date=target_date,
            target_date_supplied=target_date_supplied,
        )

    def validate_not_empty(self) -> None:
        if not any(
            (
                self.title_supplied,
                self.description_supplied,
                self.expected_outcomes_supplied,
                self.target_date_supplied,
            )
        ):
            raise EmptyGoalPatchError


@dataclass(frozen=True, slots=True)
class Goal:
    id: UUID
    organization_id: UUID
    project_id: UUID
    title: str
    description: str | None
    expected_outcomes: tuple[str, ...]
    target_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime

    def apply(self, patch: GoalPatch, *, updated_at: datetime) -> Goal:
        patch.validate_not_empty()
        return replace(
            self,
            title=patch.title if patch.title_supplied and patch.title is not None else self.title,
            description=patch.description if patch.description_supplied else self.description,
            expected_outcomes=(
                patch.expected_outcomes
                if patch.expected_outcomes_supplied
                else self.expected_outcomes
            ),
            target_date=patch.target_date if patch.target_date_supplied else self.target_date,
            version=self.version + 1,
            updated_at=updated_at,
        )
