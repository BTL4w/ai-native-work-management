"""SQLAlchemy records for immutable Project Team requirement snapshots."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.core.database import Base
from app.modules.people_capacity.adapters import database_models as _people_models
from app.modules.work.adapters import database_models as _work_models
from app.modules.work.planning.adapters import database_models as _planning_models

_PEOPLE_METADATA_LOADED = _people_models.SkillModel.__table__
_WORK_METADATA_LOADED = _work_models.TaskModel.__table__
_PLANNING_METADATA_LOADED = _planning_models.ProjectWeekModel.__table__


class TeamRequirementSetModel(Base):
    """Mutable pointer to the current immutable requirement version."""

    __tablename__ = "team_requirement_sets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
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
        ForeignKeyConstraint(
            ["organization_id", "id", "current_version"],
            [
                "team_requirement_versions.organization_id",
                "team_requirement_versions.requirement_set_id",
                "team_requirement_versions.version",
            ],
            name="fk_team_requirement_sets_current_version",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "project_id"),
        CheckConstraint("version > 0", name="ck_team_requirement_sets_version_positive"),
        CheckConstraint(
            "current_version IS NULL OR current_version > 0",
            name="ck_team_requirement_sets_current_version_positive",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'STALE')", name="ck_team_requirement_sets_status"
        ),
        Index("ix_team_requirement_sets_project", "organization_id", "project_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    project_id: Mapped[UUID]
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT", server_default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamRequirementVersionModel(Base):
    """Append-only normalized requirement snapshot."""

    __tablename__ = "team_requirement_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "requirement_set_id"],
            ["team_requirement_sets.organization_id", "team_requirement_sets.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "requirement_set_id", "version"),
        CheckConstraint("version > 0", name="ck_team_requirement_versions_version_positive"),
        CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'STALE')", name="ck_team_requirement_versions_status"
        ),
        Index(
            "ix_team_requirement_versions_history",
            "organization_id",
            "requirement_set_id",
            "version",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    requirement_set_id: Mapped[UUID]
    project_id: Mapped[UUID]
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(12))
    incomplete_items: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    task_provenance: Mapped[list[dict[str, str | int]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamRequirementItemModel(Base):
    """One canonical skill/week demand within an immutable version."""

    __tablename__ = "team_requirement_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "requirement_version_id"],
            ["team_requirement_versions.organization_id", "team_requirement_versions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "skill_id"],
            ["skills.organization_id", "skills.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_week_id"],
            ["project_weeks.organization_id", "project_weeks.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "requirement_version_id", "skill_id", "project_week_id"
        ),
        CheckConstraint("minimum_level BETWEEN 1 AND 5", name="ck_team_requirement_items_level"),
        CheckConstraint("effort_hours > 0", name="ck_team_requirement_items_effort_positive"),
        Index(
            "ix_team_requirement_items_version",
            "organization_id",
            "requirement_version_id",
            "project_week_id",
            "skill_id",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    requirement_version_id: Mapped[UUID]
    skill_id: Mapped[UUID]
    minimum_level: Mapped[int] = mapped_column(Integer)
    project_week_id: Mapped[UUID]
    effort_hours: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamRequirementTaskSourceModel(Base):
    """Task provenance frozen with the requirement item version."""

    __tablename__ = "team_requirement_task_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "requirement_item_id"],
            ["team_requirement_items.organization_id", "team_requirement_items.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "requirement_item_id", "task_id"),
        CheckConstraint(
            "task_version > 0", name="ck_team_requirement_task_sources_version_positive"
        ),
        Index(
            "ix_team_requirement_task_sources_item",
            "organization_id",
            "requirement_item_id",
            "task_id",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    requirement_item_id: Mapped[UUID]
    task_id: Mapped[UUID]
    task_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
