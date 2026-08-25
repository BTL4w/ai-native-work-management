"""Metadata contracts for tenant-safe People Skills persistence."""

from sqlalchemy import CheckConstraint, DefaultClause, ForeignKeyConstraint, UniqueConstraint

from app.core.database import Base
from app.modules.organization.adapters import database_models as organization_models
from app.modules.people_capacity.adapters import database_models as people_models
from app.modules.work.adapters import database_models as work_models

_MODEL_MODULES = (organization_models, people_models, work_models)
_TABLES = (
    "skills",
    "skill_versions",
    "person_skills",
    "skill_evidence",
    "work_outcome_evidence",
)


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


def test_people_skill_tables_are_tenant_owned_and_identity_qualified() -> None:
    for table_name in _TABLES:
        table = Base.metadata.tables[table_name]
        assert table.c.organization_id.nullable is False
        assert ("organization_id", "id") in _unique_columns(table_name)


def test_skills_and_person_skills_are_versioned_with_tenant_uniqueness() -> None:
    skills = Base.metadata.tables["skills"]
    person_skills = Base.metadata.tables["person_skills"]

    assert isinstance(skills.c.version.server_default, DefaultClause)
    assert str(skills.c.version.server_default.arg) == "1"
    assert isinstance(person_skills.c.version.server_default, DefaultClause)
    assert str(person_skills.c.version.server_default.arg) == "1"
    assert person_skills.c.active.nullable is False
    assert isinstance(person_skills.c.active.server_default, DefaultClause)
    assert str(person_skills.c.active.server_default.arg) == "true"
    assert ("organization_id", "normalized_name") in _unique_columns("skills")
    assert (
        "organization_id",
        "membership_id",
        "skill_id",
    ) in _unique_columns("person_skills")


def test_all_people_skill_references_are_tenant_qualified() -> None:
    assert _foreign_keys("skill_versions") == {
        ("organization_id", "skill_id"): ("skills.organization_id", "skills.id"),
        ("organization_id", "changed_by_membership_id"): (
            "memberships.organization_id",
            "memberships.id",
        ),
    }
    assert _foreign_keys("person_skills") == {
        ("organization_id", "membership_id"): (
            "memberships.organization_id",
            "memberships.id",
        ),
        ("organization_id", "skill_id"): ("skills.organization_id", "skills.id"),
        ("organization_id", "verified_by_membership_id"): (
            "memberships.organization_id",
            "memberships.id",
        ),
    }
    assert _foreign_keys("skill_evidence") == {
        ("organization_id", "person_skill_id"): (
            "person_skills.organization_id",
            "person_skills.id",
        ),
        ("organization_id", "source_task_id"): (
            "tasks.organization_id",
            "tasks.id",
        ),
        ("organization_id", "created_by_membership_id"): (
            "memberships.organization_id",
            "memberships.id",
        ),
    }
    assert _foreign_keys("work_outcome_evidence") == {
        ("organization_id", "membership_id"): (
            "memberships.organization_id",
            "memberships.id",
        ),
        ("organization_id", "source_task_id"): (
            "tasks.organization_id",
            "tasks.id",
        ),
        ("organization_id", "created_by_membership_id"): (
            "memberships.organization_id",
            "memberships.id",
        ),
    }


def test_people_skill_checks_enforce_level_and_task_source_consistency() -> None:
    person_skill_checks = {
        str(constraint.sqltext)
        for constraint in Base.metadata.tables["person_skills"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    skill_evidence_checks = {
        str(constraint.sqltext)
        for constraint in Base.metadata.tables["skill_evidence"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    work_evidence_checks = {
        str(constraint.sqltext)
        for constraint in Base.metadata.tables["work_outcome_evidence"].constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "level BETWEEN 1 AND 5" in person_skill_checks
    assert (
        "(source_resource_type = 'task' AND source_task_id = source_resource_id) "
        "OR (source_resource_type <> 'task' AND source_task_id IS NULL)"
    ) in skill_evidence_checks
    assert (
        "(source_resource_type = 'task' AND source_task_id = source_resource_id) "
        "OR (source_resource_type <> 'task' AND source_task_id IS NULL)"
    ) in work_evidence_checks
    assert "source_resource_version > 0" in work_evidence_checks


def test_append_only_evidence_cannot_be_deleted_through_parent_cascade() -> None:
    assert _foreign_key_deletes("skill_versions")[("organization_id", "skill_id")] == "RESTRICT"
    assert (
        _foreign_key_deletes("skill_evidence")[
            (
                "organization_id",
                "person_skill_id",
            )
        ]
        == "RESTRICT"
    )
    assert (
        _foreign_key_deletes("work_outcome_evidence")[
            (
                "organization_id",
                "membership_id",
            )
        ]
        == "RESTRICT"
    )


def test_people_skill_indexes_start_with_tenant_context() -> None:
    for table_name in _TABLES:
        for index in Base.metadata.tables[table_name].indexes:
            assert next(iter(index.columns.keys())) == "organization_id"
