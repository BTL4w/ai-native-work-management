"""Production transactions exercise immutable team lifecycle without task writes."""

import os
from dataclasses import replace
from typing import TypedDict
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.organization.domain.roles import MembershipRole
from tests.test_team_requirements_repository_integration import Case, database_case, headers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]


class RecommendationCreatePayload(TypedDict):
    requirement_set_id: str
    requirement_version: int
    policy_version: str


async def prepare(case: Case, client: AsyncClient) -> RecommendationCreatePayload:
    from app.modules.work.planning.assignment.adapters.recommendation_repository import (
        SqlAlchemyRecommendationTransactionFactory,
    )
    from app.modules.work.planning.assignment.application.recommendation_service import (
        TeamRecommendationService,
    )

    factory = async_sessionmaker(
        bind=case.connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    case.app.state.team_recommendation_service = TeamRecommendationService(
        SqlAlchemyRecommendationTransactionFactory(factory)
    )
    values = dict(
        id=uuid4(),
        capacity=uuid4(),
        org=case.actor.organization_id,
        member=case.actor.membership_id,
        skill=case.skill_id,
    )
    await case.connection.execute(
        text(
            "INSERT INTO person_skills "
            "(id,organization_id,membership_id,skill_id,level,"
            "verified_by_membership_id,verified_at) "
            "VALUES (:id,:org,:member,:skill,5,:member,now())"
        ),
        values,
    )
    await case.connection.execute(
        text(
            "INSERT INTO capacity_entries "
            "(id,organization_id,membership_id,kind,hours,effective_from,effective_to) "
            "VALUES (:capacity,:org,:member,'DEFAULT',40,'2026-01-01','2026-12-31')"
        ),
        values,
    )
    await client.post(case.url, headers=headers())
    confirmed = await client.patch(case.url, headers=headers(1), json={"action": "confirm"})
    assert confirmed.status_code == 200, confirmed.text
    response = confirmed.json()
    return {
        "requirement_set_id": str(response["id"]),
        "requirement_version": 2,
        "policy_version": "ranking-v1",
    }


@pytest.mark.asyncio
async def test_lifecycle_exact_replay_immutable_versions_and_zero_task_assignments():
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        task_before = (
            await case.connection.execute(
                text("SELECT assignee_membership_id, version FROM tasks WHERE id=:id"),
                {"id": case.task_id},
            )
        ).one()
        url = f"/api/v1/projects/{case.project_id}/team-recommendations"
        create_headers = headers()
        created = await client.post(url, headers=create_headers, json=payload)
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["version"] == 1 and len(first["selections"]) == 1
        root = f"/api/v1/recommendations/{first['recommendation_id']}"
        revision = await client.patch(root, headers=headers(1), json={"overrides": []})
        assert revision.status_code == 200, revision.text
        assert revision.json()["version"] == 2 and revision.json()["selections"] == []
        assert (await client.get(root + "/versions/1")).json() == first
        stale = await client.post(root + "/approve", headers=headers(1), json={"action": "approve"})
        assert stale.status_code == 412
        restore = await client.patch(
            root,
            headers=headers(2),
            json={
                "overrides": [
                    {
                        "requirement_id": first["selections"][0]["requirement_id"],
                        "selected_membership_id": str(case.actor.membership_id),
                    }
                ]
            },
        )
        assert restore.status_code == 200, restore.text
        approve_headers = headers(3)
        approved = await client.post(
            root + "/approve", headers=approve_headers, json={"action": "approve"}
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "APPROVED"
        replay = await client.post(
            root + "/approve", headers=approve_headers, json={"action": "approve"}
        )
        assert replay.json() == approved.json() and replay.headers["Idempotency-Replayed"] == "true"
        assert (await client.post(url, headers=create_headers, json=payload)).json() == first
        assert (await client.get(root + "/versions/1")).json() == first
        team = await client.get(f"/api/v1/projects/{case.project_id}/team")
        assert team.status_code == 200 and len(team.json()["memberships"]) == 1
        task_after = (
            await case.connection.execute(
                text("SELECT assignee_membership_id, version FROM tasks WHERE id=:id"),
                {"id": case.task_id},
            )
        ).one()
        assert task_after == task_before
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM recommendation_decisions")) == 1
        )
        assert (
            await case.connection.scalar(
                text(
                    "SELECT count(*) FROM outbox_events "
                    "WHERE event_type='team_recommendation.approved.v1' "
                    "AND payload->>'version'='3'"
                )
            )
            == 1
        )
        await case.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_feedback_is_not_approval_and_rejection_creates_no_team():
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
        root = f"/api/v1/recommendations/{created.json()['recommendation_id']}"
        feedback = await client.post(
            root + "/feedback",
            headers=headers(),
            json={"version": 1, "kind": "accept", "comment": "Looks good"},
        )
        assert feedback.status_code == 201, feedback.text
        assert (await client.get(root)).json()["status"] == "PROPOSED"
        rejected = await client.post(
            root + "/approve",
            headers=headers(1),
            json={"action": "reject", "reason": "Budget changed"},
        )
        assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM project_team_memberships")) == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["inactive", "role", "skill", "requirement", "policy"])
async def test_approval_revalidates_current_facts_atomically(change: str) -> None:
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
        root = f"/api/v1/recommendations/{created.json()['recommendation_id']}"
        statements = {
            "inactive": "UPDATE memberships SET is_active=false",
            "role": "UPDATE memberships SET role='EMPLOYEE'",
            "skill": "UPDATE person_skills SET active=false",
            "requirement": "UPDATE tasks SET version=version+1",
            "policy": "UPDATE skills SET active=false",
        }
        await case.connection.execute(text("RESET ROLE"))
        await case.connection.execute(text(statements[change]))
        result = await client.post(
            root + "/approve", headers=headers(1), json={"action": "approve"}
        )
        assert result.status_code in (403, 409, 422), result.text
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM project_team_memberships")) == 0
        )
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM recommendation_decisions")) == 0
        )
        assert (
            await case.connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE outcome='REJECTED'")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_employee_malformed_mutation_is_denied_and_audited():
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        await prepare(case, client)
        employee = replace(case.actor, role=MembershipRole.EMPLOYEE)
        case.app.dependency_overrides[get_authenticated_actor] = lambda: employee
        response = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            content="{",
        )
        assert response.status_code == 403
        assert (
            await case.connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE outcome='REJECTED'")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_unrelated_manager_cannot_create_recommendation_for_project():
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        other_user, other_member = uuid4(), uuid4()
        await case.connection.execute(text("RESET ROLE"))
        await case.connection.execute(
            text(
                "INSERT INTO users "
                "(id,email_normalized,email_display,display_name,password_hash) VALUES "
                "(:user,:email,:email,'Other manager','unused')"
            ),
            {"user": other_user, "email": f"{other_user}@example.test"},
        )
        await case.connection.execute(
            text(
                "INSERT INTO memberships (id,organization_id,user_id,role) "
                "VALUES (:member,:organization_id,:user,'MANAGER')"
            ),
            {
                "member": other_member,
                "organization_id": case.actor.organization_id,
                "user": other_user,
            },
        )
        unrelated = replace(
            case.actor, membership_id=other_member, user_id=other_user, email=str(other_user)
        )
        case.app.dependency_overrides[get_authenticated_actor] = lambda: unrelated

        response = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            json=payload,
        )

        assert response.status_code == 403, response.text
        assert await case.connection.scalar(text("SELECT count(*) FROM recommendations")) == 0
        assert (
            await case.connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE outcome='REJECTED'")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_create_rejects_idempotency_key_reuse_with_different_version() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        url = f"/api/v1/projects/{case.project_id}/team-recommendations"
        request_headers = headers()
        created = await client.post(url, headers=request_headers, json=payload)
        assert created.status_code == 201, created.text

        changed = await client.post(
            url,
            headers=request_headers,
            json={**payload, "requirement_version": payload["requirement_version"] + 1},
        )

        assert changed.status_code == 409, changed.text
        assert changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        assert await case.connection.scalar(text("SELECT count(*) FROM recommendations")) == 1


@pytest.mark.asyncio
async def test_historical_version_zero_is_rejected() -> None:
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
        recommendation_id = created.json()["recommendation_id"]

        response = await client.get(f"/api/v1/recommendations/{recommendation_id}/versions/0")

        assert response.status_code == 422


@pytest.mark.asyncio
async def test_stale_proposal_can_be_rejected_and_replayed_without_memberships() -> None:
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
        original = created.json()
        root = f"/api/v1/recommendations/{original['recommendation_id']}"
        await case.connection.execute(text("RESET ROLE"))
        await case.connection.execute(
            text("UPDATE tasks SET version=version+1 WHERE id=:task_id"),
            {"task_id": case.task_id},
        )
        decision_headers = headers(1)

        rejected = await client.post(
            root + "/approve",
            headers=decision_headers,
            json={"action": "reject", "reason": "Inputs changed"},
        )
        replay = await client.post(
            root + "/approve",
            headers=decision_headers,
            json={"action": "reject", "reason": "Inputs changed"},
        )

        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "REJECTED"
        assert replay.json() == rejected.json()
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert (await client.get(root + "/versions/1")).json() == original
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM project_team_memberships")) == 0
        )


@pytest.mark.asyncio
async def test_inactive_top_user_is_filtered_before_allocating_to_active_alternative() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        inactive_member, inactive_user = UUID(int=1), uuid4()
        await case.connection.execute(text("RESET ROLE"))
        values = {
            "organization_id": case.actor.organization_id,
            "manager_id": case.actor.membership_id,
            "member_id": inactive_member,
            "user_id": inactive_user,
            "email": f"{inactive_user}@example.test",
            "person_skill_id": uuid4(),
            "skill_id": case.skill_id,
            "capacity_id": uuid4(),
        }
        for statement in (
            "INSERT INTO users "
            "(id,email_normalized,email_display,display_name,password_hash,is_active) VALUES "
            "(:user_id,:email,:email,'Inactive','unused',false)",
            "INSERT INTO memberships (id,organization_id,user_id,role) "
            "VALUES (:member_id,:organization_id,:user_id,'EMPLOYEE')",
            "INSERT INTO person_skills "
            "(id,organization_id,membership_id,skill_id,level,verified_by_membership_id,"
            "verified_at) VALUES "
            "(:person_skill_id,:organization_id,:member_id,:skill_id,5,:manager_id,now())",
            "INSERT INTO capacity_entries "
            "(id,organization_id,membership_id,kind,hours,effective_from,effective_to) VALUES "
            "(:capacity_id,:organization_id,:member_id,'DEFAULT',40,'2026-01-01','2026-12-31')",
        ):
            await case.connection.execute(text(statement), values)

        created = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            json=payload,
        )

        assert created.status_code == 201, created.text
        body = created.json()
        assert body["uncovered"] == []
        assert [item["membership_id"] for item in body["selections"]] == [
            str(case.actor.membership_id)
        ]
        inactive = next(
            item for item in body["alternatives"] if item["membership_id"] == str(inactive_member)
        )
        assert inactive["eligible"] is False
        assert "INACTIVE_MEMBER" in inactive["hard_failure_codes"]
        activation = await case.connection.scalar(
            text(
                "SELECT input_snapshot->'candidate_activation' "
                "FROM recommendation_versions WHERE recommendation_id=:recommendation_id"
            ),
            {"recommendation_id": body["recommendation_id"]},
        )
        assert any(
            item["membership_id"] == str(inactive_member) and item["user_active"] is False
            for item in activation
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["membership", "user", "skill", "leave", "capacity"])
async def test_current_status_is_stale_after_selected_candidate_facts_change(change: str) -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        employee_id, user_id = UUID(int=1), uuid4()
        values = {
            "organization_id": case.actor.organization_id,
            "manager_id": case.actor.membership_id,
            "member_id": employee_id,
            "user_id": user_id,
            "email": f"{user_id}@example.test",
            "person_skill_id": uuid4(),
            "skill_id": case.skill_id,
            "capacity_id": uuid4(),
            "leave_id": uuid4(),
        }
        await case.connection.execute(text("RESET ROLE"))
        for statement in (
            "INSERT INTO users "
            "(id,email_normalized,email_display,display_name,password_hash) VALUES "
            "(:user_id,:email,:email,'Candidate','unused')",
            "INSERT INTO memberships (id,organization_id,user_id,role) "
            "VALUES (:member_id,:organization_id,:user_id,'EMPLOYEE')",
            "INSERT INTO person_skills "
            "(id,organization_id,membership_id,skill_id,level,verified_by_membership_id,"
            "verified_at) VALUES "
            "(:person_skill_id,:organization_id,:member_id,:skill_id,5,:manager_id,now())",
            "INSERT INTO capacity_entries "
            "(id,organization_id,membership_id,kind,hours,effective_from,effective_to) VALUES "
            "(:capacity_id,:organization_id,:member_id,'DEFAULT',40,'2026-01-01','2026-12-31')",
        ):
            await case.connection.execute(text(statement), values)
        created = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            json=payload,
        )
        original = created.json()
        assert original["selections"][0]["membership_id"] == str(employee_id)
        root = f"/api/v1/recommendations/{original['recommendation_id']}"
        await case.connection.execute(text("RESET ROLE"))
        statements = {
            "membership": "UPDATE memberships SET is_active=false WHERE id=:member_id",
            "user": "UPDATE users SET is_active=false WHERE id=:user_id",
            "skill": "UPDATE person_skills SET active=false WHERE id=:person_skill_id",
            "capacity": "UPDATE capacity_entries SET hours=0 WHERE id=:capacity_id",
            "leave": "INSERT INTO leave_entries "
            "(id,organization_id,membership_id,start_date,end_date,unavailable_hours) "
            "VALUES (:leave_id,:organization_id,:member_id,'2026-09-07','2026-09-13',40)",
        }
        await case.connection.execute(text(statements[change]), values)

        current = await client.get(root)

        assert current.status_code == 200
        assert current.json()["status"] == "STALE"
        assert (await client.get(root + "/versions/1")).json() == original


@pytest.mark.asyncio
async def test_unchanged_split_capacity_proposal_approves_without_override_reasons() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        payload = await prepare(case, client)
        employee_id, user_id = UUID(int=1), uuid4()
        values = {
            "organization_id": case.actor.organization_id,
            "manager_id": case.actor.membership_id,
            "member_id": employee_id,
            "user_id": user_id,
            "email": f"{user_id}@example.test",
            "person_skill_id": uuid4(),
            "skill_id": case.skill_id,
            "capacity_id": uuid4(),
        }
        await case.connection.execute(text("RESET ROLE"))
        await case.connection.execute(
            text("UPDATE capacity_entries SET hours=4 WHERE membership_id=:manager_id"), values
        )
        for statement in (
            "INSERT INTO users "
            "(id,email_normalized,email_display,display_name,password_hash) VALUES "
            "(:user_id,:email,:email,'Candidate','unused')",
            "INSERT INTO memberships (id,organization_id,user_id,role) "
            "VALUES (:member_id,:organization_id,:user_id,'EMPLOYEE')",
            "INSERT INTO person_skills "
            "(id,organization_id,membership_id,skill_id,level,verified_by_membership_id,"
            "verified_at) VALUES "
            "(:person_skill_id,:organization_id,:member_id,:skill_id,5,:manager_id,now())",
            "INSERT INTO capacity_entries "
            "(id,organization_id,membership_id,kind,hours,effective_from,effective_to) VALUES "
            "(:capacity_id,:organization_id,:member_id,'DEFAULT',4,'2026-01-01','2026-12-31')",
        ):
            await case.connection.execute(text(statement), values)
        created = await client.post(
            f"/api/v1/projects/{case.project_id}/team-recommendations",
            headers=headers(),
            json=payload,
        )
        body = created.json()
        assert sorted(item["allocated_effort_hours"] for item in body["selections"]) == ["4", "4"]
        assert all(item["override_reason"] is None for item in body["selections"])

        approved = await client.post(
            f"/api/v1/recommendations/{body['recommendation_id']}/approve",
            headers=headers(1),
            json={"action": "approve"},
        )

        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "APPROVED"
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM project_team_memberships")) == 2
        )
