"""Populated PostgreSQL RLS, provenance, and append-only recommendation checks."""

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_team_recommendation_api_integration import prepare
from tests.test_team_requirements_repository_integration import database_case, headers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]

TABLES = (
    "recommendations",
    "recommendation_versions",
    "candidate_scores",
    "recommendation_selections",
    "recommendation_feedback",
    "recommendation_decisions",
    "project_team_memberships",
)
HISTORY_TABLES = TABLES[1:-1]


@pytest.mark.asyncio
async def test_populated_recommendation_rows_are_tenant_isolated_and_history_is_append_only() -> (
    None
):
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        created = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            json=payload,
        )
        assert created.status_code == 201, created.text
        recommendation_id = created.json()["recommendation_id"]
        root = f"/api/v1/recommendations/{recommendation_id}"
        feedback = await client.post(
            root + "/feedback",
            headers=headers(),
            json={"version": 1, "kind": "accept", "comment": "Accepted"},
        )
        approved = await client.post(
            root + "/approve", headers=headers(1), json={"action": "approve"}
        )
        assert feedback.status_code == 201, feedback.text
        assert approved.status_code == 200, approved.text

        await case.connection.execute(text("RESET ROLE"))
        await case.connection.execute(text("SET LOCAL ROLE app_runtime"))
        await case.connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(uuid4())},
        )
        for table in TABLES:
            assert await case.connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        hidden_update = await case.connection.execute(
            text("UPDATE recommendation_versions SET policy_version='changed'")
        )
        assert hidden_update.rowcount == 0

        await case.connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(case.actor.organization_id)},
        )
        for table in HISTORY_TABLES:
            row_id = await case.connection.scalar(text(f"SELECT id FROM {table} LIMIT 1"))
            assert row_id is not None
            with pytest.raises(DBAPIError, match="append-only"):
                async with case.connection.begin_nested():
                    await case.connection.execute(
                        text(f"UPDATE {table} SET id=id WHERE id=:row_id"),
                        {"row_id": row_id},
                    )
            with pytest.raises(DBAPIError, match="append-only"):
                async with case.connection.begin_nested():
                    await case.connection.execute(
                        text(f"DELETE FROM {table} WHERE id=:row_id"), {"row_id": row_id}
                    )


@pytest.mark.asyncio
async def test_database_rejects_team_membership_from_rejection_decision() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        created = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            json=payload,
        )
        root = f"/api/v1/recommendations/{created.json()['recommendation_id']}"
        rejected = await client.post(
            root + "/approve",
            headers=headers(1),
            json={"action": "reject", "reason": "Changed scope"},
        )
        assert rejected.status_code == 200, rejected.text
        row = (
            await case.connection.execute(
                text(
                    "SELECT id, recommendation_version_id FROM recommendation_decisions "
                    "WHERE action='reject'"
                )
            )
        ).one()
        await case.connection.execute(text("RESET ROLE"))
        with pytest.raises(DBAPIError):
            async with case.connection.begin_nested():
                await case.connection.execute(
                    text(
                        "INSERT INTO project_team_memberships "
                        "(id,organization_id,project_id,membership_id,decision_id,"
                        "recommendation_version_id,decision_action,active) VALUES "
                        "(:id,:organization_id,:project_id,:membership_id,:decision_id,"
                        ":version_id,'approve',true)"
                    ),
                    {
                        "id": uuid4(),
                        "organization_id": case.actor.organization_id,
                        "project_id": case.project_id,
                        "membership_id": case.actor.membership_id,
                        "decision_id": row.id,
                        "version_id": row.recommendation_version_id,
                    },
                )


@pytest.mark.asyncio
async def test_database_rejects_second_active_membership_for_same_project_person() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        created = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            json=payload,
        )
        root = f"/api/v1/recommendations/{created.json()['recommendation_id']}"
        approved = await client.post(
            root + "/approve", headers=headers(1), json={"action": "approve"}
        )
        assert approved.status_code == 200, approved.text
        row = (
            await case.connection.execute(
                text("SELECT decision_id,recommendation_version_id FROM project_team_memberships")
            )
        ).one()
        await case.connection.execute(text("RESET ROLE"))
        with pytest.raises(DBAPIError):
            async with case.connection.begin_nested():
                await case.connection.execute(
                    text(
                        "INSERT INTO project_team_memberships "
                        "(id,organization_id,project_id,membership_id,decision_id,"
                        "recommendation_version_id,decision_action,active) VALUES "
                        "(:id,:organization_id,:project_id,:membership_id,:decision_id,"
                        ":version_id,'approve',true)"
                    ),
                    {
                        "id": uuid4(),
                        "organization_id": case.actor.organization_id,
                        "project_id": case.project_id,
                        "membership_id": case.actor.membership_id,
                        "decision_id": row.decision_id,
                        "version_id": row.recommendation_version_id,
                    },
                )
