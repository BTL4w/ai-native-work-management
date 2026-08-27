"""Skill taxonomy, verified person skills, and evidence invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import IntEnum, StrEnum
from uuid import UUID


class SkillLevel(IntEnum):
    """Verified skill proficiency on the fixed Phase 3 scale."""

    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4
    LEVEL_5 = 5


class SkillEvidenceType(StrEnum):
    """Evidence kinds permitted to support a verified skill."""

    MANAGER_NOTE = "MANAGER_NOTE"
    CERTIFICATE = "CERTIFICATE"
    COMPLETED_TASK = "COMPLETED_TASK"
    REVIEW_OUTCOME = "REVIEW_OUTCOME"


class PeopleSkillError(Exception):
    """Base class for expected People Skills domain failures."""


class PeopleSkillForbiddenError(PeopleSkillError):
    """The actor may not mutate People Skills data."""


class PeopleSkillNotFoundError(PeopleSkillError):
    """A People Skills resource is absent or invisible to the actor."""


class PeopleSkillReferenceError(PeopleSkillError):
    """A tenant-owned member or evidence source is invalid."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class PeopleSkillConflictError(PeopleSkillError):
    """A unique People Skills fact already exists."""


class InvalidSkillFieldError(PeopleSkillError):
    """A Skill or verified person-skill field violates its boundary."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class InvalidSkillLevelError(PeopleSkillError):
    """A proficiency value is outside the fixed one-to-five scale."""

    def __init__(self) -> None:
        super().__init__("level")
        self.field = "level"


class InvalidEvidenceFieldError(PeopleSkillError):
    """An evidence field is unsafe, unsupported, or lacks provenance."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class EmptySkillPatchError(PeopleSkillError):
    """A Skill update supplied no mutable field."""


class EmptyPersonSkillPatchError(PeopleSkillError):
    """A verified person-skill update supplied no mutable field."""


class PeopleSkillIdempotencyKeyReusedError(PeopleSkillError):
    """An idempotency key was reused for different People Skills input."""


class PeopleSkillVersionMismatchError(PeopleSkillError):
    """A stale mutation attempted to overwrite a verified person skill."""

    def __init__(self, current_version: int) -> None:
        super().__init__(current_version)
        self.current_version = current_version


def _skill_name(value: str) -> tuple[str, str]:
    display_name = value.strip()
    if not 1 <= len(display_name) <= 100:
        raise InvalidSkillFieldError("name")
    normalized_name = " ".join(display_name.lower().split())
    if not normalized_name:
        raise InvalidSkillFieldError("name")
    return display_name, normalized_name


def _skill_description(value: str | None) -> str | None:
    if value is None:
        return None
    description = value.strip()
    if len(description) > 2_000:
        raise InvalidSkillFieldError("description")
    return description or None


def _skill_level(value: int) -> SkillLevel:
    if type(value) is not int:
        raise InvalidSkillLevelError
    try:
        return SkillLevel(value)
    except ValueError as error:
        raise InvalidSkillLevelError from error


def _evidence_type(value: SkillEvidenceType | str) -> SkillEvidenceType:
    try:
        return SkillEvidenceType(value)
    except ValueError as error:
        raise InvalidEvidenceFieldError("evidence_type") from error


def _evidence_summary(value: str) -> str:
    summary = value.strip()
    if not 1 <= len(summary) <= 2_000:
        raise InvalidEvidenceFieldError("summary")
    return summary


def _source_resource_type(value: str) -> str:
    source_resource_type = " ".join(value.lower().split())
    if not 1 <= len(source_resource_type) <= 100:
        raise InvalidEvidenceFieldError("source_resource_type")
    return source_resource_type


def _aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidEvidenceFieldError(field)
    return value


def _skill_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidSkillFieldError(field)
    return value


def _source_resource_version(value: int) -> int:
    if type(value) is not int or value < 1:
        raise InvalidEvidenceFieldError("source_resource_version")
    return value


@dataclass(frozen=True, slots=True)
class SkillDraft:
    """Validated values for a new organization Skill."""

    name: str
    normalized_name: str
    description: str | None

    @classmethod
    def create(cls, *, name: str, description: str | None) -> SkillDraft:
        display_name, normalized_name = _skill_name(name)
        return cls(
            name=display_name,
            normalized_name=normalized_name,
            description=_skill_description(description),
        )


@dataclass(frozen=True, slots=True)
class SkillPatch:
    """Validated partial Skill changes with explicit null semantics."""

    name: str | None = None
    normalized_name: str | None = None
    name_supplied: bool = False
    description: str | None = None
    description_supplied: bool = False
    active: bool | None = None
    active_supplied: bool = False

    @classmethod
    def create(
        cls,
        *,
        name: str | None = None,
        name_supplied: bool = False,
        description: str | None = None,
        description_supplied: bool = False,
        active: bool | None = None,
        active_supplied: bool = False,
    ) -> SkillPatch:
        effective_name_supplied = name_supplied or name is not None
        effective_active_supplied = active_supplied or active is not None
        if effective_name_supplied and name is None:
            raise InvalidSkillFieldError("name")
        if effective_active_supplied and active is None:
            raise InvalidSkillFieldError("active")
        normalized_name: str | None = None
        display_name: str | None = None
        if name is not None:
            display_name, normalized_name = _skill_name(name)
        return cls(
            name=display_name,
            normalized_name=normalized_name,
            name_supplied=effective_name_supplied,
            description=(_skill_description(description) if description_supplied else None),
            description_supplied=description_supplied,
            active=active,
            active_supplied=effective_active_supplied,
        )

    def validate_not_empty(self) -> None:
        if not any((self.name_supplied, self.description_supplied, self.active_supplied)):
            raise EmptySkillPatchError


@dataclass(frozen=True, slots=True)
class Skill:
    """Current tenant-owned Skill definition."""

    id: UUID
    organization_id: UUID
    name: str
    normalized_name: str
    description: str | None
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    def apply(self, patch: SkillPatch, *, updated_at: datetime) -> Skill:
        patch.validate_not_empty()
        normalized_updated_at = _skill_datetime(updated_at, field="updated_at")
        return replace(
            self,
            name=patch.name if patch.name_supplied and patch.name is not None else self.name,
            normalized_name=(
                patch.normalized_name
                if patch.name_supplied and patch.normalized_name is not None
                else self.normalized_name
            ),
            description=patch.description if patch.description_supplied else self.description,
            active=(
                patch.active if patch.active_supplied and patch.active is not None else self.active
            ),
            version=self.version + 1,
            updated_at=normalized_updated_at,
        )


@dataclass(frozen=True, slots=True)
class SkillEvidenceDraft:
    """Normalized evidence to append to a verified person skill."""

    evidence_type: SkillEvidenceType
    summary: str
    source_resource_type: str
    source_resource_id: UUID
    occurred_at: datetime

    @classmethod
    def create(
        cls,
        *,
        evidence_type: SkillEvidenceType | str,
        summary: str,
        source_resource_type: str,
        source_resource_id: UUID,
        occurred_at: datetime,
    ) -> SkillEvidenceDraft:
        return cls(
            evidence_type=_evidence_type(evidence_type),
            summary=_evidence_summary(summary),
            source_resource_type=_source_resource_type(source_resource_type),
            source_resource_id=source_resource_id,
            occurred_at=_aware_datetime(occurred_at, field="occurred_at"),
        )


@dataclass(frozen=True, slots=True)
class SkillEvidence:
    """Append-only evidence persisted for a verified person skill."""

    id: UUID
    organization_id: UUID
    person_skill_id: UUID
    evidence_type: SkillEvidenceType
    summary: str
    source_resource_type: str
    source_resource_id: UUID
    occurred_at: datetime
    created_by_membership_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PersonSkillDraft:
    """Validated values for creating or replacing a verified person skill."""

    membership_id: UUID
    skill_id: UUID
    level: SkillLevel
    verified_by_membership_id: UUID
    evidence: tuple[SkillEvidenceDraft, ...]

    @classmethod
    def create(
        cls,
        *,
        membership_id: UUID,
        skill_id: UUID,
        level: int,
        verified_by_membership_id: UUID | None,
        evidence: tuple[SkillEvidenceDraft, ...],
    ) -> PersonSkillDraft:
        if verified_by_membership_id is None:
            raise InvalidSkillFieldError("verified_by_membership_id")
        normalized_evidence = tuple(evidence)
        if len(normalized_evidence) > 20:
            raise InvalidEvidenceFieldError("evidence")
        return cls(
            membership_id=membership_id,
            skill_id=skill_id,
            level=_skill_level(level),
            verified_by_membership_id=verified_by_membership_id,
            evidence=normalized_evidence,
        )


@dataclass(frozen=True, slots=True)
class PersonSkillPatch:
    """A re-verification and optional evidence append for a person skill."""

    level: SkillLevel | None = None
    level_supplied: bool = False
    verified_by_membership_id: UUID | None = None
    evidence: tuple[SkillEvidenceDraft, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        level: int | None = None,
        level_supplied: bool = False,
        verified_by_membership_id: UUID | None = None,
        evidence: tuple[SkillEvidenceDraft, ...] = (),
    ) -> PersonSkillPatch:
        effective_level_supplied = level_supplied or level is not None
        normalized_evidence = tuple(evidence)
        if len(normalized_evidence) > 20:
            raise InvalidEvidenceFieldError("evidence")
        if effective_level_supplied and level is None:
            raise InvalidSkillLevelError
        if (effective_level_supplied or normalized_evidence) and verified_by_membership_id is None:
            raise InvalidSkillFieldError("verified_by_membership_id")
        return cls(
            level=_skill_level(level) if level is not None else None,
            level_supplied=effective_level_supplied,
            verified_by_membership_id=verified_by_membership_id,
            evidence=normalized_evidence,
        )

    def validate_not_empty(self) -> None:
        if not self.level_supplied and not self.evidence:
            raise EmptyPersonSkillPatchError


@dataclass(frozen=True, slots=True)
class VerifiedPersonSkill:
    """Current verified proficiency for one member and Skill."""

    id: UUID
    organization_id: UUID
    membership_id: UUID
    skill_id: UUID
    level: SkillLevel
    verified_by_membership_id: UUID
    verified_at: datetime
    version: int
    created_at: datetime
    updated_at: datetime
    active: bool = True

    def apply(
        self,
        patch: PersonSkillPatch,
        *,
        verified_at: datetime,
        updated_at: datetime,
    ) -> VerifiedPersonSkill:
        patch.validate_not_empty()
        if patch.verified_by_membership_id is None:
            raise InvalidSkillFieldError("verified_by_membership_id")
        normalized_verified_at = _skill_datetime(verified_at, field="verified_at")
        normalized_updated_at = _skill_datetime(updated_at, field="updated_at")
        return replace(
            self,
            level=(patch.level if patch.level_supplied and patch.level is not None else self.level),
            verified_by_membership_id=patch.verified_by_membership_id,
            verified_at=normalized_verified_at,
            version=self.version + 1,
            updated_at=normalized_updated_at,
        )


@dataclass(frozen=True, slots=True)
class WorkOutcomeEvidenceDraft:
    """Relevant completed-work or review evidence with exact provenance."""

    evidence_type: SkillEvidenceType
    summary: str
    source_resource_type: str
    source_resource_id: UUID
    source_resource_version: int
    observed_at: datetime

    @classmethod
    def create(
        cls,
        *,
        evidence_type: SkillEvidenceType | str,
        summary: str,
        source_resource_type: str,
        source_resource_id: UUID,
        source_resource_version: int,
        observed_at: datetime,
    ) -> WorkOutcomeEvidenceDraft:
        normalized_type = _evidence_type(evidence_type)
        normalized_source_type = _source_resource_type(source_resource_type)
        expected_source_types = {
            SkillEvidenceType.COMPLETED_TASK: "task",
            SkillEvidenceType.REVIEW_OUTCOME: "review",
        }
        expected_source_type = expected_source_types.get(normalized_type)
        if expected_source_type is None:
            raise InvalidEvidenceFieldError("evidence_type")
        if normalized_source_type != expected_source_type:
            raise InvalidEvidenceFieldError("source_resource_type")
        return cls(
            evidence_type=normalized_type,
            summary=_evidence_summary(summary),
            source_resource_type=normalized_source_type,
            source_resource_id=source_resource_id,
            source_resource_version=_source_resource_version(source_resource_version),
            observed_at=_aware_datetime(observed_at, field="observed_at"),
        )


@dataclass(frozen=True, slots=True)
class WorkOutcomeEvidence:
    """Append-only contextual work evidence, never a global person score."""

    id: UUID
    organization_id: UUID
    membership_id: UUID
    evidence_type: SkillEvidenceType
    summary: str
    source_resource_type: str
    source_resource_id: UUID
    source_resource_version: int
    observed_at: datetime
    created_by_membership_id: UUID
    created_at: datetime
