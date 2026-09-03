"""Metadata contracts for tenant-safe capacity and leave persistence."""

from sqlalchemy import CheckConstraint, DefaultClause, ForeignKeyConstraint, UniqueConstraint

from app.core.database import Base
from app.modules.organization.adapters import database_models as organization_models
from app.modules.people_capacity.adapters import database_models as people_models
from app.modules.work.adapters import database_models as work_models

_MODEL_MODULES = (organization_models, people_models, work_models)
_TABLES = ("capacity_entries", "leave_entries")


def _unique_columns(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(constraint.columns.keys())
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_keys(table_name: str) -> dict[tuple[str, ...], tuple[str, ...]]:
    return {
        tuple(constraint.column_keys): tuple(
            element.target_fullname for element in constraint.elements
        )
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _foreign_key_deletes(table_name: str) -> dict[tuple[str, ...], str | None]:
    return {
        tuple(constraint.column_keys): constraint.ondelete
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def test_capacity_and_leave_tables_are_tenant_owned_and_identity_qualified() -> None:
    for table_name in _TABLES:
        table = Base.metadata.tables[table_name]
        assert table.c.organization_id.nullable is False
        assert ("organization_id", "id") in _unique_columns(table_name)


def test_capacity_and_leave_are_versioned_with_server_defaults() -> None:
    for table_name in _TABLES:
        table = Base.metadata.tables[table_name]
        assert isinstance(table.c.version.server_default, DefaultClause)
        assert str(table.c.version.server_default.arg) == "1"


def test_capacity_and_leave_foreign_keys_are_tenant_qualified_and_cascade() -> None:
    for table_name in _TABLES:
        assert _foreign_keys(table_name) == {
            ("organization_id", "membership_id"): (
                "memberships.organization_id",
                "memberships.id",
            ),
        }
        assert _foreign_key_deletes(table_name) == {
            ("organization_id", "membership_id"): "CASCADE",
        }


def test_capacity_and_leave_check_constraints_enforce_hour_and_date_boundaries() -> None:
    capacity_checks = {
        constraint.name
        for constraint in Base.metadata.tables["capacity_entries"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    leave_checks = {
        constraint.name
        for constraint in Base.metadata.tables["leave_entries"].constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_capacity_entries_hours" in capacity_checks
    assert "ck_capacity_entries_dates" in capacity_checks
    assert "ck_leave_entries_hours" in leave_checks
    assert "ck_leave_entries_dates" in leave_checks


def test_capacity_override_has_tenant_scoped_unique_index() -> None:
    table = Base.metadata.tables["capacity_entries"]
    override_indexes = [
        index
        for index in table.indexes
        if index.unique
        and tuple(c.name for c in index.columns)
        == ("organization_id", "membership_id", "week_start")
    ]
    assert len(override_indexes) == 1


def test_capacity_default_has_tenant_scoped_unique_index() -> None:
    table = Base.metadata.tables["capacity_entries"]
    default_indexes = [
        index
        for index in table.indexes
        if index.unique
        and tuple(column.name for column in index.columns) == ("organization_id", "membership_id")
        and str(index.dialect_options["postgresql"]["where"]) == "kind = 'DEFAULT'"
    ]
    assert len(default_indexes) == 1
