"""Metadata contracts for tenant-owned Tasks and status history."""

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.core.database import Base
from app.modules.work.adapters import database_models as work_models

_MODEL_MODULES = (work_models,)


def test_task_tables_are_registered_and_tenant_owned() -> None:
    for table_name in ("tasks", "task_status_transitions"):
        assert Base.metadata.tables[table_name].c.organization_id.nullable is False


def test_tasks_use_tenant_qualified_project_assignee_and_actor_references() -> None:
    tasks = Base.metadata.tables["tasks"]
    foreign_keys = {
        tuple(constraint.column_keys): tuple(e.target_fullname for e in constraint.elements)
        for constraint in tasks.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys[("organization_id", "project_id")] == (
        "projects.organization_id",
        "projects.id",
    )
    assert foreign_keys[("organization_id", "assignee_membership_id")] == (
        "memberships.organization_id",
        "memberships.id",
    )
    assert foreign_keys[("organization_id", "milestone_id")] == (
        "milestones.organization_id",
        "milestones.id",
    )
    assert ("organization_id", "id") in {
        tuple(c.columns.keys()) for c in tasks.constraints if isinstance(c, UniqueConstraint)
    }


def test_task_indexes_start_with_tenant_and_transition_is_append_only_shaped() -> None:
    tasks = Base.metadata.tables["tasks"]
    indexes = {tuple(index.columns.keys()) for index in tasks.indexes}
    assert ("organization_id", "project_id", "status", "id") in indexes
    assert ("organization_id", "assignee_membership_id", "status", "due_date", "id") in indexes
    assert ("organization_id", "milestone_id", "id") in indexes

    transitions = Base.metadata.tables["task_status_transitions"]
    assert "updated_at" not in transitions.c
    assert "task_version_after" in transitions.c
