"""SQLAlchemy models for tenant-scoped planning resources."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


def _actor_foreign_keys() -> tuple[ForeignKeyConstraint, ForeignKeyConstraint]:
    return (
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
    )


class GoalModel(Base):
    __tablename__ = "goals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
        *_actor_foreign_keys(),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "project_id"),
        Index("ix_goals_project", "organization_id", "project_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    project_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    expected_outcomes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    target_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MilestoneModel(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
        *_actor_foreign_keys(),
        UniqueConstraint("organization_id", "id"),
        CheckConstraint("position > 0", name="ck_milestones_position_positive"),
        Index("ix_milestones_project_position", "organization_id", "project_id", "position", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    project_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    target_date: Mapped[date | None] = mapped_column(Date)
    position: Mapped[int]
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskDependencyModel(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "predecessor_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "successor_task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        *_actor_foreign_keys(),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "predecessor_task_id", "successor_task_id"),
        CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name="ck_task_dependencies_not_self",
        ),
        Index("ix_task_dependencies_predecessor", "organization_id", "predecessor_task_id", "id"),
        Index("ix_task_dependencies_successor", "organization_id", "successor_task_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    predecessor_task_id: Mapped[UUID]
    successor_task_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AcceptanceCriterionModel(Base):
    __tablename__ = "acceptance_criteria"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            ondelete="CASCADE",
        ),
        *_actor_foreign_keys(),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "task_id", "text"),
        CheckConstraint("position > 0", name="ck_acceptance_criteria_position_positive"),
        Index(
            "ix_acceptance_criteria_task_position", "organization_id", "task_id", "position", "id"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    task_id: Mapped[UUID]
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int]
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
