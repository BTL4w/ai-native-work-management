"""SQLAlchemy models for tenant-owned People Skills persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base
from app.modules.organization.adapters import database_models as _organization_models
from app.modules.people_capacity.domain.skills import SkillEvidenceType
from app.modules.work.adapters import database_models as _work_models

_ORGANIZATION_METADATA_LOADED = _organization_models.MembershipModel.__table__
_WORK_METADATA_LOADED = _work_models.TaskModel.__table__


class SkillModel(Base):
    """Current organization-owned Skill definition."""

    __tablename__ = "skills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "updated_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "normalized_name"),
        Index("ix_skills_catalog", "organization_id", "active", "normalized_name", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillVersionModel(Base):
    """Append-only snapshot for each persisted Skill version."""

    __tablename__ = "skill_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "skill_id"],
            ["skills.organization_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "changed_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "skill_id", "version"),
        Index("ix_skill_versions_history", "organization_id", "skill_id", "version", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    skill_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    changed_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersonSkillModel(Base):
    """Current verified Skill level for one organization membership."""

    __tablename__ = "person_skills"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 5", name="level_range"),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "skill_id"],
            ["skills.organization_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "verified_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "membership_id", "skill_id"),
        Index(
            "ix_person_skills_candidate_lookup",
            "organization_id",
            "skill_id",
            "level",
            "membership_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    skill_id: Mapped[UUID]
    level: Mapped[int] = mapped_column(Integer)
    verified_by_membership_id: Mapped[UUID]
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillEvidenceModel(Base):
    """Append-only provenance supporting one verified person Skill."""

    __tablename__ = "skill_evidence"
    __table_args__ = (
        CheckConstraint(
            "(source_resource_type = 'task' AND source_task_id = source_resource_id) "
            "OR (source_resource_type <> 'task' AND source_task_id IS NULL)",
            name="task_source_consistency",
        ),
        ForeignKeyConstraint(
            ["organization_id", "person_skill_id"],
            ["person_skills.organization_id", "person_skills.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        Index(
            "ix_skill_evidence_timeline",
            "organization_id",
            "person_skill_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_skill_evidence_source",
            "organization_id",
            "source_resource_type",
            "source_resource_id",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    person_skill_id: Mapped[UUID]
    evidence_type: Mapped[SkillEvidenceType] = mapped_column(
        SQLAlchemyEnum(SkillEvidenceType, name="skill_evidence_type", validate_strings=True)
    )
    summary: Mapped[str] = mapped_column(Text)
    source_resource_type: Mapped[str] = mapped_column(String(100))
    source_resource_id: Mapped[UUID]
    source_task_id: Mapped[UUID | None]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkOutcomeEvidenceModel(Base):
    """Append-only contextual outcome evidence without a person score."""

    __tablename__ = "work_outcome_evidence"
    __table_args__ = (
        CheckConstraint(
            "evidence_type IN ('COMPLETED_TASK', 'REVIEW_OUTCOME')",
            name="type",
        ),
        CheckConstraint(
            "(source_resource_type = 'task' AND source_task_id = source_resource_id) "
            "OR (source_resource_type <> 'task' AND source_task_id IS NULL)",
            name="task_source_consistency",
        ),
        CheckConstraint(
            "source_resource_version > 0",
            name="source_version_positive",
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id",
            "membership_id",
            "evidence_type",
            "source_resource_id",
            "source_resource_version",
        ),
        Index(
            "ix_work_outcome_evidence_timeline",
            "organization_id",
            "membership_id",
            "observed_at",
            "id",
        ),
        Index(
            "ix_work_outcome_evidence_source",
            "organization_id",
            "source_resource_type",
            "source_resource_id",
            "source_resource_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    evidence_type: Mapped[SkillEvidenceType] = mapped_column(
        SQLAlchemyEnum(SkillEvidenceType, name="skill_evidence_type", validate_strings=True)
    )
    summary: Mapped[str] = mapped_column(Text)
    source_resource_type: Mapped[str] = mapped_column(String(100))
    source_resource_id: Mapped[UUID]
    source_task_id: Mapped[UUID | None]
    source_resource_version: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
