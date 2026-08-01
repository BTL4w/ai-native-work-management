"""SQLAlchemy models for tenant-scoped Projects and idempotent mutations."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class IdempotencyState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ProjectModel(Base):
    """Tenant-owned Project persistence record."""

    __tablename__ = "projects"
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
        Index("ix_projects_timeline", "organization_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_membership_id: Mapped[UUID]
    updated_by_membership_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRecordModel(Base):
    """Stable replay record scoped to one tenant actor and operation."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "actor_membership_id", "operation", "idempotency_key"),
        Index("ix_idempotency_records_expiry", "organization_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    actor_membership_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[IdempotencyState] = mapped_column(
        SQLAlchemyEnum(IdempotencyState, name="idempotency_state", validate_strings=True)
    )
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
