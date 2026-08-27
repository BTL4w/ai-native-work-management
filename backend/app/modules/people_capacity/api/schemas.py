"""Strict public schemas for Skills and verified person Skills."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.people_capacity.domain.skills import (
    Skill,
    SkillEvidence,
    SkillEvidenceType,
    VerifiedPersonSkill,
    WorkOutcomeEvidence,
)


class SkillCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2_000)


class SkillUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2_000)
    active: bool | None = None


class SkillResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    normalized_name: str
    description: str | None
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, value: Skill) -> Self:
        return cls(**{field: getattr(value, field) for field in cls.model_fields})


class SkillEvidenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_type: SkillEvidenceType
    summary: str = Field(min_length=1, max_length=2_000)
    source_resource_type: str = Field(min_length=1, max_length=100)
    source_resource_id: UUID
    occurred_at: datetime


class SkillEvidenceResponse(BaseModel):
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

    @classmethod
    def from_domain(cls, value: SkillEvidence) -> Self:
        return cls(**{field: getattr(value, field) for field in cls.model_fields})


class PersonSkillUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: UUID
    level: int = Field(ge=1, le=5)
    evidence: list[SkillEvidenceCreateRequest] = Field(
        default_factory=lambda: list[SkillEvidenceCreateRequest](), max_length=20
    )


class PersonSkillResponse(BaseModel):
    id: UUID
    organization_id: UUID
    membership_id: UUID
    skill_id: UUID
    level: int
    verified_by_membership_id: UUID
    verified_at: datetime
    version: int
    created_at: datetime
    updated_at: datetime
    active: bool
    evidence: list[SkillEvidenceResponse]

    @classmethod
    def from_domain(cls, value: VerifiedPersonSkill, evidence: tuple[SkillEvidence, ...]) -> Self:
        values = {field: getattr(value, field) for field in cls.model_fields if field != "evidence"}
        return cls(
            **values,
            evidence=[SkillEvidenceResponse.from_domain(item) for item in evidence],
        )


class WorkOutcomeEvidenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_type: SkillEvidenceType
    summary: str = Field(min_length=1, max_length=2_000)
    source_resource_type: str = Field(min_length=1, max_length=100)
    source_resource_id: UUID
    source_resource_version: int = Field(ge=1)
    observed_at: datetime


class WorkOutcomeEvidenceResponse(BaseModel):
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

    @classmethod
    def from_domain(cls, value: WorkOutcomeEvidence) -> Self:
        return cls(**{field: getattr(value, field) for field in cls.model_fields})
