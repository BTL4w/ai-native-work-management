"""Tenant identity and exact history binding are database contracts."""

from sqlalchemy import ForeignKeyConstraint, Numeric, UniqueConstraint

from app.core.database import Base
from app.modules.work.planning.assignment.adapters import recommendation_models

assert recommendation_models.RecommendationModel

TABLES = (
    "recommendations",
    "recommendation_versions",
    "candidate_scores",
    "recommendation_selections",
    "recommendation_feedback",
    "recommendation_decisions",
    "project_team_memberships",
)


def test_recommendation_tables_have_tenant_qualified_keys():
    assert set(TABLES) <= set(Base.metadata.tables)
    for name in TABLES:
        table = Base.metadata.tables[name]
        assert not table.c.organization_id.nullable
        assert any(
            isinstance(c, UniqueConstraint) and tuple(c.columns.keys()) == ("organization_id", "id")
            for c in table.constraints
        )
        assert all(
            c.column_keys[0] == "organization_id"
            for c in table.constraints
            if isinstance(c, ForeignKeyConstraint)
        )
        assert all(next(iter(i.columns.keys())) == "organization_id" for i in table.indexes)


def test_team_membership_is_unique_and_separate_from_task_assignment():
    assert "project_team_memberships" in Base.metadata.tables
    table = Base.metadata.tables["project_team_memberships"]
    assert any(
        i.unique and tuple(i.columns.keys()) == ("organization_id", "project_id", "membership_id")
        for i in table.indexes
    )
    assert "task_id" not in table.c


def test_team_membership_database_provenance_requires_approved_exact_version():
    table = Base.metadata.tables["project_team_memberships"]
    assert {"recommendation_version_id", "decision_action"} <= set(table.c.keys())
    assert table.c.decision_action.server_default is not None
    assert "approve" in str(table.c.decision_action.server_default)
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and tuple(constraint.column_keys)
        == (
            "organization_id",
            "decision_id",
            "project_id",
            "recommendation_version_id",
            "decision_action",
        )
        for constraint in table.constraints
    )


def test_allocated_effort_uses_bounded_decimal_storage():
    column_type = Base.metadata.tables["recommendation_selections"].c.allocated_effort_hours.type
    assert isinstance(column_type, Numeric)
    assert column_type.precision == 20
    assert column_type.scale == 4
