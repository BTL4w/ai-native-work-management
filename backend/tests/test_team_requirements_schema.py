"""Metadata contracts for versioned, tenant-safe team requirements."""

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.core.database import Base


def _foreign_keys(table_name: str) -> dict[tuple[str, ...], tuple[str, ...]]:
    return {
        tuple(constraint.column_keys): tuple(
            element.target_fullname for element in constraint.elements
        )
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _unique_columns(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(constraint.columns.keys())
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_team_requirement_tables_are_tenant_owned_with_composite_references() -> None:
    expected = {
        "team_requirement_sets",
        "team_requirement_versions",
        "team_requirement_items",
        "team_requirement_task_sources",
    }
    assert expected <= set(Base.metadata.tables)
    for table_name in expected:
        table = Base.metadata.tables[table_name]
        assert table.c.organization_id.nullable is False
        assert ("organization_id", "id") in _unique_columns(table_name)
        assert all("organization_id" in key for key in _foreign_keys(table_name))


def test_requirement_item_references_skill_and_week_inside_same_tenant() -> None:
    foreign_keys = _foreign_keys("team_requirement_items")
    assert foreign_keys[("organization_id", "skill_id")] == (
        "skills.organization_id",
        "skills.id",
    )
    assert foreign_keys[("organization_id", "project_week_id")] == (
        "project_weeks.organization_id",
        "project_weeks.id",
    )


def test_requirement_sources_reference_same_tenant_task_and_version_items_are_unique() -> None:
    foreign_keys = _foreign_keys("team_requirement_task_sources")
    assert foreign_keys[("organization_id", "task_id")] == (
        "tasks.organization_id",
        "tasks.id",
    )
    assert (
        "organization_id",
        "requirement_version_id",
        "skill_id",
        "project_week_id",
    ) in _unique_columns("team_requirement_items")


def test_current_pointer_contract_rejects_cross_set_or_wrong_version_targets() -> None:
    table = Base.metadata.tables["team_requirement_sets"]
    foreign_keys = _foreign_keys("team_requirement_sets")
    assert "current_version_id" not in table.c
    assert table.c.current_version.nullable is True
    assert foreign_keys[("organization_id", "id", "current_version")] == (
        "team_requirement_versions.organization_id",
        "team_requirement_versions.requirement_set_id",
        "team_requirement_versions.version",
    )
    pointer = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(constraint.column_keys) == ("organization_id", "id", "current_version")
    )
    assert pointer.deferrable is True
    assert pointer.initially == "DEFERRED"
    assert (
        "organization_id",
        "requirement_set_id",
        "version",
    ) in _unique_columns("team_requirement_versions")


def test_requirement_version_freezes_all_project_task_identity_and_versions() -> None:
    table = Base.metadata.tables["team_requirement_versions"]
    assert table.c.task_provenance.nullable is False
