"""Tenant-qualified roots and append-only decision evidence."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base
from app.modules.work.planning.assignment.adapters import database_models as _requirements

_REQUIREMENTS_LOADED = _requirements.TeamRequirementVersionModel.__table__


class RecommendationModel(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "id", "current_version"],
            [
                "recommendation_versions.organization_id",
                "recommendation_versions.recommendation_id",
                "recommendation_versions.version",
            ],
            name="fk_recommendations_current_version",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "status IN ('PROPOSED','APPROVED','REJECTED','STALE')", name="ck_recommendations_status"
        ),
        CheckConstraint("current_version > 0", name="ck_recommendations_version"),
        Index("ix_recommendations_project", "organization_id", "project_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    project_id: Mapped[UUID]
    current_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecommendationVersionModel(Base):
    __tablename__ = "recommendation_versions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "recommendation_id", "version"),
        ForeignKeyConstraint(
            ["organization_id", "recommendation_id"],
            ["recommendations.organization_id", "recommendations.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "requirement_set_id", "requirement_version"],
            [
                "team_requirement_versions.organization_id",
                "team_requirement_versions.requirement_set_id",
                "team_requirement_versions.version",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        CheckConstraint("version > 0", name="ck_recommendation_versions_version"),
        Index(
            "ix_recommendation_versions_history", "organization_id", "recommendation_id", "version"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    recommendation_id: Mapped[UUID]
    version: Mapped[int]
    requirement_set_id: Mapped[UUID]
    requirement_version: Mapped[int]
    policy_version: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateScoreModel(Base):
    __tablename__ = "candidate_scores"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "recommendation_version_id", "requirement_id", "membership_id"
        ),
        ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id"],
            ["recommendation_versions.organization_id", "recommendation_versions.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "requirement_id"],
            ["team_requirement_items.organization_id", "team_requirement_items.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"], ["memberships.organization_id", "memberships.id"]
        ),
        Index("ix_candidate_scores_version", "organization_id", "recommendation_version_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    recommendation_version_id: Mapped[UUID]
    requirement_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)


class RecommendationSelectionModel(Base):
    __tablename__ = "recommendation_selections"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "recommendation_version_id", "requirement_id", "membership_id"
        ),
        ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id", "requirement_id", "membership_id"],
            [
                "candidate_scores.organization_id",
                "candidate_scores.recommendation_version_id",
                "candidate_scores.requirement_id",
                "candidate_scores.membership_id",
            ],
        ),
        CheckConstraint("allocated_effort_hours > 0", name="ck_recommendation_selections_effort"),
        Index(
            "ix_recommendation_selections_version", "organization_id", "recommendation_version_id"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    recommendation_version_id: Mapped[UUID]
    requirement_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    allocated_effort_hours: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    warning_codes: Mapped[list[str]] = mapped_column(JSONB)
    override_reason: Mapped[str | None] = mapped_column(String(500))


class RecommendationFeedbackModel(Base):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id"],
            ["recommendation_versions.organization_id", "recommendation_versions.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        CheckConstraint(
            "kind IN ('accept','override','reject')", name="ck_recommendation_feedback_kind"
        ),
        Index("ix_recommendation_feedback_version", "organization_id", "recommendation_version_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    recommendation_version_id: Mapped[UUID]
    actor_membership_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(12))
    comment: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecommendationDecisionModel(Base):
    __tablename__ = "recommendation_decisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "recommendation_version_id"),
        UniqueConstraint(
            "organization_id",
            "id",
            "project_id",
            "recommendation_version_id",
            "action",
        ),
        ForeignKeyConstraint(
            ["organization_id", "recommendation_version_id"],
            ["recommendation_versions.organization_id", "recommendation_versions.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
        ),
        CheckConstraint(
            "action IN ('approve','reject')", name="ck_recommendation_decisions_action"
        ),
        Index(
            "ix_recommendation_decisions_version", "organization_id", "recommendation_version_id"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    recommendation_version_id: Mapped[UUID]
    project_id: Mapped[UUID]
    actor_membership_id: Mapped[UUID]
    action: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectTeamMembershipModel(Base):
    __tablename__ = "project_team_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"], ["memberships.organization_id", "memberships.id"]
        ),
        ForeignKeyConstraint(
            [
                "organization_id",
                "decision_id",
                "project_id",
                "recommendation_version_id",
                "decision_action",
            ],
            [
                "recommendation_decisions.organization_id",
                "recommendation_decisions.id",
                "recommendation_decisions.project_id",
                "recommendation_decisions.recommendation_version_id",
                "recommendation_decisions.action",
            ],
        ),
        CheckConstraint("decision_action = 'approve'", name="ck_project_team_approved"),
        Index(
            "uq_project_team_active",
            "organization_id",
            "project_id",
            "membership_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    project_id: Mapped[UUID]
    membership_id: Mapped[UUID]
    decision_id: Mapped[UUID]
    recommendation_version_id: Mapped[UUID]
    decision_action: Mapped[str] = mapped_column(String(12), server_default="approve")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
