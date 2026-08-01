"""SQLAlchemy model for append-only tenant audit evidence."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, func, text
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.audit.domain.events import AuditOutcome


class AuditEventModel(Base):
    """Allowlisted audit evidence; secrets and raw credentials never belong here."""

    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "actor_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_audit_events_timeline", "organization_id", "occurred_at", "id"),
        Index(
            "ix_audit_events_resource",
            "organization_id",
            "resource_type",
            "resource_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    actor_membership_id: Mapped[UUID | None]
    action: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[AuditOutcome] = mapped_column(
        SQLAlchemyEnum(AuditOutcome, name="audit_outcome", validate_strings=True)
    )
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[UUID | None]
    request_id: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    before_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    after_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    reason_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
