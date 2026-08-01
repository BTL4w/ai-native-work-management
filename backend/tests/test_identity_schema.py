"""Metadata contract tests for the identity and organization schema."""

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.core.database import Base
from app.modules.audit.adapters import database_models as audit_models
from app.modules.identity.adapters import database_models as identity_models
from app.modules.organization.adapters import database_models as organization_models
from app.modules.work.adapters import database_models as work_models

_MODEL_MODULES = (audit_models, identity_models, organization_models, work_models)


def test_identity_and_organization_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "organizations",
        "users",
        "memberships",
        "auth_sessions",
        "audit_events",
        "projects",
        "idempotency_records",
        "tasks",
        "task_status_transitions",
    }


def test_tenant_tables_require_organization_id() -> None:
    for table_name in ("memberships", "auth_sessions", "audit_events"):
        column = Base.metadata.tables[table_name].c.organization_id
        assert column.nullable is False


def test_membership_has_tenant_scoped_uniqueness() -> None:
    memberships = Base.metadata.tables["memberships"]
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in memberships.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("organization_id", "id") in unique_columns
    assert ("organization_id", "user_id") in unique_columns


def test_auth_session_uses_composite_tenant_foreign_key() -> None:
    auth_sessions = Base.metadata.tables["auth_sessions"]
    foreign_keys = [
        constraint
        for constraint in auth_sessions.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]

    assert len(foreign_keys) == 1
    assert tuple(foreign_keys[0].column_keys) == ("organization_id", "membership_id")
    assert tuple(element.target_fullname for element in foreign_keys[0].elements) == (
        "memberships.organization_id",
        "memberships.id",
    )


def test_audit_event_actor_uses_composite_tenant_foreign_key() -> None:
    audit_events = Base.metadata.tables["audit_events"]
    foreign_keys = [
        constraint
        for constraint in audit_events.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]

    assert len(foreign_keys) == 1
    assert tuple(foreign_keys[0].column_keys) == (
        "organization_id",
        "actor_membership_id",
    )
    assert tuple(element.target_fullname for element in foreign_keys[0].elements) == (
        "memberships.organization_id",
        "memberships.id",
    )
