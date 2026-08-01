"""Metadata contract tests for tenant-owned Projects and idempotency."""

from sqlalchemy import DefaultClause, ForeignKeyConstraint, UniqueConstraint

from app.core.database import Base
from app.modules.work.adapters import database_models as work_models

_MODEL_MODULES = (work_models,)


def _unique_columns(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_project_tables_are_tenant_owned_and_versioned() -> None:
    projects = Base.metadata.tables["projects"]
    idempotency = Base.metadata.tables["idempotency_records"]

    assert projects.c.organization_id.nullable is False
    assert idempotency.c.organization_id.nullable is False
    assert isinstance(projects.c.version.server_default, DefaultClause)
    assert str(projects.c.version.server_default.arg) == "1"


def test_project_has_tenant_uniqueness_and_actor_foreign_keys() -> None:
    projects = Base.metadata.tables["projects"]
    foreign_keys = {
        tuple(constraint.column_keys): tuple(
            element.target_fullname for element in constraint.elements
        )
        for constraint in projects.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert ("organization_id", "id") in _unique_columns("projects")
    assert foreign_keys[("organization_id", "created_by_membership_id")] == (
        "memberships.organization_id",
        "memberships.id",
    )
    assert foreign_keys[("organization_id", "updated_by_membership_id")] == (
        "memberships.organization_id",
        "memberships.id",
    )


def test_idempotency_uniqueness_is_scoped_to_tenant_actor_and_operation() -> None:
    assert (
        "organization_id",
        "actor_membership_id",
        "operation",
        "idempotency_key",
    ) in _unique_columns("idempotency_records")


def test_project_timeline_index_starts_with_tenant() -> None:
    projects = Base.metadata.tables["projects"]
    indexes = {tuple(index.columns.keys()) for index in projects.indexes}

    assert ("organization_id", "created_at", "id") in indexes
