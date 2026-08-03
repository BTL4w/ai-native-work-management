"""Acceptance Criterion values and deterministic field invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID


class AcceptanceCriterionError(Exception):
    """Base class for expected Acceptance Criterion failures."""


class InvalidAcceptanceCriterionError(AcceptanceCriterionError):
    def __init__(self, field: str = "text") -> None:
        super().__init__(field)
        self.field = field


class EmptyAcceptanceCriterionPatchError(AcceptanceCriterionError):
    """An Acceptance Criterion patch supplied no mutable field."""


def _text(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 1000:
        raise InvalidAcceptanceCriterionError("text")
    return normalized


def _position(value: int) -> int:
    if value < 1:
        raise InvalidAcceptanceCriterionError("position")
    return value


@dataclass(frozen=True, slots=True)
class AcceptanceCriterionDraft:
    task_id: UUID
    text: str
    position: int

    @classmethod
    def create(
        cls,
        *,
        task_id: UUID,
        text: str,
        position: int,
    ) -> AcceptanceCriterionDraft:
        return cls(task_id=task_id, text=_text(text), position=_position(position))


@dataclass(frozen=True, slots=True)
class AcceptanceCriterionPatch:
    text: str | None = None
    text_supplied: bool = False
    position: int | None = None
    position_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        text: str | None = None,
        text_supplied: bool = False,
        position: int | None = None,
        position_supplied: bool = False,
    ) -> AcceptanceCriterionPatch:
        effective_text = text_supplied or text is not None
        effective_position = position_supplied or position is not None
        if effective_text and text is None:
            raise InvalidAcceptanceCriterionError("text")
        if effective_position and position is None:
            raise InvalidAcceptanceCriterionError("position")
        return cls(
            text=_text(text) if text is not None else None,
            text_supplied=effective_text,
            position=_position(position) if position is not None else None,
            position_supplied=effective_position,
        )

    def validate_not_empty(self) -> None:
        if not self.text_supplied and not self.position_supplied:
            raise EmptyAcceptanceCriterionPatchError


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    id: UUID
    organization_id: UUID
    task_id: UUID
    text: str
    position: int
    version: int
    created_at: datetime
    updated_at: datetime

    def apply(
        self,
        patch: AcceptanceCriterionPatch,
        *,
        updated_at: datetime,
    ) -> AcceptanceCriterion:
        patch.validate_not_empty()
        return replace(
            self,
            text=patch.text if patch.text_supplied and patch.text is not None else self.text,
            position=(
                patch.position
                if patch.position_supplied and patch.position is not None
                else self.position
            ),
            version=self.version + 1,
            updated_at=updated_at,
        )
