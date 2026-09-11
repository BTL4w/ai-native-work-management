"""Real PostgreSQL lifecycle, rejection atomicity and tenant isolation."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from app.core.config import Settings
from app.core.database import create_database_engine
from app.main import create_app
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.assignment.adapters.repository import (
    SqlAlchemyTeamRequirementTransactionFactory,
)
from app.modules.work.planning.assignment.application.requirement_service import (
    TeamRequirementService,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]


@dataclass
class Case:
    connection: AsyncConnection
    app: FastAPI
    actor: AuthenticatedActor
    project_id: UUID
    task_id: UUID
    week_id: UUID
    skill_id: UUID

    @property
    def url(self) -> str:
        return f"/api/v1/projects/{self.project_id}/team-requirements"


@asynccontextmanager
async def database_case() -> AsyncGenerator[Case]:
    """Production service transactions use savepoints; all fixture data rolls back."""
    settings = Settings(environment="test")
    engine = create_database_engine(settings)
    org, member, user, project, week, skill, task = (uuid4() for _ in range(7))
    actor = AuthenticatedActor(
        organization_id=org,
        membership_id=member,
        user_id=user,
        email=f"{user}@example.test",
        display_name="Manager",
        organization_name="Test",
        role=MembershipRole.MANAGER,
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            values = dict(
                org=org,
                member=member,
                user=user,
                project=project,
                week=week,
                skill=skill,
                task=task,
                slug=str(org),
                email=actor.email,
            )
            statements = (
                "INSERT INTO organizations (id,slug,name) VALUES (:org,:slug,'Test')",
                "INSERT INTO users (id,email_normalized,email_display,display_name,password_hash) "
                "VALUES (:user,:email,:email,'Manager','unused')",
                "INSERT INTO memberships (id,organization_id,user_id,role) "
                "VALUES (:member,:org,:user,'MANAGER')",
                "INSERT INTO projects (id,organization_id,name,created_by_membership_id,"
                "updated_by_membership_id) VALUES (:project,:org,'Project',:member,:member)",
                "INSERT INTO project_weeks (id,organization_id,project_id,week_number,start_date,"
                "end_date,objective,created_by_membership_id,updated_by_membership_id) "
                "VALUES (:week,:org,:project,1,'2026-09-07','2026-09-13','Launch',:member,:member)",
                "INSERT INTO skills (id,organization_id,name,normalized_name,"
                "created_by_membership_id,updated_by_membership_id) "
                "VALUES (:skill,:org,'Research','research',:member,:member)",
                "INSERT INTO tasks (id,organization_id,project_id,project_week_id,title,status,"
                "required_skill_labels,estimated_effort_hours,created_by_membership_id,"
                "updated_by_membership_id) VALUES (:task,:org,:project,:week,'Discovery','TO_DO',"
                "'[\"Research\"]',8,:member,:member)",
            )
            for statement in statements:
                await connection.execute(text(statement), values)
            factory = async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                autoflush=False,
                join_transaction_mode="create_savepoint",
            )
            app = create_app(
                settings,
                team_requirement_service=TeamRequirementService(
                    SqlAlchemyTeamRequirementTransactionFactory(factory)
                ),
            )
            app.dependency_overrides[get_authenticated_actor] = lambda: actor
            try:
                yield Case(connection, app, actor, project, task, week, skill)
            finally:
                await transaction.rollback()
                await app.state.database_engine.dispose()
    finally:
        await engine.dispose()


def headers(version: int | None = None) -> dict[str, str]:
    result = {"Idempotency-Key": str(uuid4())}
    if version is not None:
        result["If-Match"] = f'"{version}"'
    return result


@pytest.mark.asyncio
async def test_multi_item_revision_replays_the_exact_original_response() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        created = await client.post(case.url, headers=headers())
        second_skill = uuid4()
        await case.connection.execute(
            text(
                "INSERT INTO skills (id,organization_id,name,normalized_name,"
                "created_by_membership_id,updated_by_membership_id) "
                "VALUES (:id,:org,'Review','review',:member,:member)"
            ),
            {
                "id": second_skill,
                "org": case.actor.organization_id,
                "member": case.actor.membership_id,
            },
        )
        item = created.json()["items"][0]
        item.pop("id")
        items = sorted(
            [item, {**item, "skill_id": str(second_skill)}],
            key=lambda value: value["skill_id"],
            reverse=True,
        )
        revision_headers = headers(1)
        payload = {"action": "revise", "items": items}
        revised = await client.patch(case.url, headers=revision_headers, json=payload)
        assert revised.status_code == 200, revised.text
        replay = await client.patch(case.url, headers=revision_headers, json=payload)
        assert replay.json() == revised.json()
        assert (await client.get(case.url)).json() == revised.json()


@pytest.mark.asyncio
async def test_postgres_lifecycle_preserves_edits_exact_replay_and_one_outbox() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        derive_headers = headers()
        created = await client.post(case.url, headers=derive_headers)
        assert created.status_code == 201, created.text
        item = created.json()["items"][0]
        assert item["effort_hours"] == 8
        item.pop("id")
        item.update(minimum_level=3, effort_hours=12)
        revised = await client.patch(
            case.url,
            headers=headers(1),
            json={
                "action": "revise",
                "items": [item],
            },
        )
        assert revised.status_code == 200, revised.text
        confirm_headers = headers(2)
        confirmed = await client.patch(
            case.url, headers=confirm_headers, json={"action": "confirm"}
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "CONFIRMED"
        assert confirmed.json()["items"][0]["effort_hours"] == 12
        assert confirmed.json()["items"][0]["minimum_level"] == 3
        replay = await client.patch(case.url, headers=confirm_headers, json={"action": "confirm"})
        assert replay.json() == confirmed.json()
        assert replay.headers["Idempotency-Replayed"] == "true"
        original = await client.post(case.url, headers=derive_headers)
        assert original.json() == created.json()
        stale = await client.patch(case.url, headers=headers(1), json={"action": "confirm"})
        assert stale.status_code == 412
        assert (await client.get(case.url)).json() == confirmed.json()
        await case.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert await case.connection.scalar(text("SELECT count(*) FROM outbox_events")) == 1
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM team_requirement_versions"))
            == 3
        )
        assert (
            await case.connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE outcome='REJECTED'")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_postgres_ranking_preview_is_reproducible_and_employee_project_scoped() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        employee_member, employee_user, person_skill, capacity, other_member, other_user = (
            uuid4() for _ in range(6)
        )
        values = {
            "org": case.actor.organization_id,
            "manager": case.actor.membership_id,
            "member": employee_member,
            "user": employee_user,
            "person_skill": person_skill,
            "capacity": capacity,
            "skill": case.skill_id,
            "task": case.task_id,
            "email": f"{employee_user}@example.test",
            "other_member": other_member,
            "other_user": other_user,
            "other_email": f"{other_user}@example.test",
        }
        for statement in (
            "INSERT INTO users (id,email_normalized,email_display,display_name,password_hash) "
            "VALUES (:user,:email,:email,'Lan','unused')",
            "INSERT INTO memberships (id,organization_id,user_id,role) "
            "VALUES (:member,:org,:user,'EMPLOYEE')",
            "INSERT INTO users (id,email_normalized,email_display,display_name,password_hash) "
            "VALUES (:other_user,:other_email,:other_email,'Minh','unused')",
            "INSERT INTO memberships (id,organization_id,user_id,role) "
            "VALUES (:other_member,:org,:other_user,'EMPLOYEE')",
            "INSERT INTO person_skills (id,organization_id,membership_id,skill_id,level,"
            "verified_by_membership_id,verified_at) VALUES "
            "(:person_skill,:org,:member,:skill,5,:manager,now())",
            "INSERT INTO capacity_entries (id,organization_id,membership_id,kind,hours,"
            "effective_from,effective_to) VALUES "
            "(:capacity,:org,:member,'DEFAULT',16,'2026-01-01','2026-12-31')",
            "UPDATE tasks SET assignee_membership_id=:member WHERE id=:task",
        ):
            await case.connection.execute(text(statement), values)

        created = await client.post(case.url, headers=headers())
        assert created.status_code == 201, created.text
        employee = replace(
            case.actor,
            membership_id=employee_member,
            user_id=employee_user,
            email=values["email"],
            display_name="Lan",
            role=MembershipRole.EMPLOYEE,
        )
        case.app.dependency_overrides[get_authenticated_actor] = lambda: employee
        first = await client.get(f"{case.url}/ranking-preview")
        second = await client.get(f"{case.url}/ranking-preview")

        assert first.status_code == 200, first.text
        assert first.json() == second.json()
        lan = next(row for row in first.json()["candidates"] if row["display_name"] == "Lan")
        assert {row["membership_id"] for row in first.json()["candidates"]} == {
            str(employee_member)
        }
        assert all(
            row["membership_id"] == str(employee_member) for row in first.json()["allocations"]
        )
        assert lan["eligible"] is True
        assert lan["skill_points"] == "0.5000"
        assert lan["capacity_points"] == "0.3000"
        assert lan["residual_capacity_hours"] == 8


@pytest.mark.asyncio
async def test_postgres_refresh_rederives_changed_task_facts() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        created = await client.post(case.url, headers=headers())
        assert created.status_code == 201
        await case.connection.execute(
            text("UPDATE tasks SET estimated_effort_hours=13, version=2 WHERE id=:task"),
            {"task": case.task_id},
        )
        stale = await client.patch(case.url, headers=headers(1), json={"action": "confirm"})
        assert stale.json()["status"] == "STALE"

        refresh_headers = headers(2)
        refreshed = await client.patch(
            case.url, headers=refresh_headers, json={"action": "refresh"}
        )
        replay = await client.patch(case.url, headers=refresh_headers, json={"action": "refresh"})

        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "DRAFT"
        assert refreshed.json()["version"] == 3
        assert refreshed.json()["items"][0]["effort_hours"] == 13
        assert replay.json() == refreshed.json()
        assert replay.headers["Idempotency-Replayed"] == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["duplicate", "overflow", "foreign_skill", "foreign_week", "foreign_task", "incomplete"]
)
async def test_postgres_rejected_revision_is_atomic_and_audited(kind: str) -> None:
    async with (
        database_case() as case,
        AsyncClient(
            transport=ASGITransport(app=case.app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client,
    ):
        created = await client.post(case.url, headers=headers())
        assert created.status_code == 201, created.text
        item = created.json()["items"][0]
        item.pop("id")
        payload = {"action": "revise", "items": [item]}
        if kind == "duplicate":
            payload["items"] = [item, item]
        elif kind == "overflow":
            item["effort_hours"] = 2147483648
        elif kind == "foreign_skill":
            item["skill_id"] = str(uuid4())
        elif kind == "foreign_week":
            item["project_week_id"] = str(uuid4())
        elif kind == "foreign_task":
            item["source_task_ids"] = [str(uuid4())]
        else:
            payload["incomplete_items"] = [{"task_id": str(uuid4()), "reason": "missing"}]
        rejected = await client.patch(case.url, headers=headers(1), json=payload)
        assert rejected.status_code == 422, rejected.text
        assert (await client.get(case.url)).json() == created.json()
        assert (
            await case.connection.scalar(text("SELECT count(*) FROM team_requirement_versions"))
            == 1
        )
        assert await case.connection.scalar(text("SELECT count(*) FROM outbox_events")) == 0
        assert (
            await case.connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE outcome='REJECTED'")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_task_version_drift_stales_confirmation_without_outbox() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        assert (await client.post(case.url, headers=headers())).status_code == 201
        await case.connection.execute(
            text("UPDATE tasks SET version=2 WHERE id=:id"), {"id": case.task_id}
        )
        response = await client.patch(case.url, headers=headers(1), json={"action": "confirm"})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "STALE"
        denied = await client.patch(case.url, headers=headers(2), json={"action": "confirm"})
        assert denied.status_code == 422
        assert await case.connection.scalar(text("SELECT count(*) FROM outbox_events")) == 0


@pytest.mark.asyncio
async def test_real_rows_are_hidden_cross_tenant_and_history_is_immutable() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        assert (await client.post(case.url, headers=headers())).status_code == 201
        tables = (
            "team_requirement_sets",
            "team_requirement_versions",
            "team_requirement_items",
            "team_requirement_task_sources",
        )
        for table in tables:
            assert await case.connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1
            # Clone all required values, changing only tenant and row identity.
            columns = list((await case.connection.execute(text(f"SELECT * FROM {table}"))).keys())
            projection = [
                ":new_id"
                if column == "id"
                else ":foreign_org"
                if column == "organization_id"
                else column
                for column in columns
            ]
            with pytest.raises(DBAPIError) as denied:
                async with case.connection.begin_nested():
                    await case.connection.execute(
                        text(
                            f"INSERT INTO {table} ({', '.join(columns)}) "
                            f"SELECT {', '.join(projection)} FROM {table}"
                        ),
                        {"new_id": uuid4(), "foreign_org": uuid4()},
                    )
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        for table in tables[1:]:
            for operation in (f"UPDATE {table} SET id=id", f"DELETE FROM {table}"):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with case.connection.begin_nested():
                        await case.connection.execute(text(operation))
        for tenant in (str(uuid4()), ""):
            await case.connection.execute(
                text("SELECT set_config('app.organization_id',:org,true)"), {"org": tenant}
            )
            for table in tables:
                assert await case.connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        await case.connection.execute(
            text("SELECT set_config('app.organization_id',:org,true)"),
            {"org": str(case.actor.organization_id)},
        )
        # Fully populated row: assert the RLS SQLSTATE, not a missing-column error.
        with pytest.raises(DBAPIError) as raised:
            async with case.connection.begin_nested():
                await case.connection.execute(
                    text(
                        "INSERT INTO team_requirement_sets (id,organization_id,project_id,"
                        "created_by_membership_id,updated_by_membership_id) "
                        "VALUES (:id,:org,:project,:member,:member)"
                    ),
                    {
                        "id": uuid4(),
                        "org": uuid4(),
                        "project": case.project_id,
                        "member": case.actor.membership_id,
                    },
                )
        assert getattr(raised.value.orig, "sqlstate", None) == "42501"
        foreign = replace(case.actor, organization_id=uuid4())
        case.app.dependency_overrides[get_authenticated_actor] = lambda: foreign
        assert (await client.get(case.url)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["json", "key", "uuid", "body"])
async def test_postgres_transport_rejections_leave_one_audit(kind: str) -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        url = case.url if kind != "uuid" else "/api/v1/projects/not-a-uuid/team-requirements"
        request_headers = headers() if kind != "key" else {}
        response = await client.post(
            url,
            headers={**request_headers, "Content-Type": "application/json"},
            content="{" if kind == "json" else '{"unexpected":true}' if kind == "body" else "null",
        )
        assert response.status_code == 422
        assert await case.connection.scalar(text("SELECT count(*) FROM team_requirement_sets")) == 0
        assert (
            await case.connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE outcome='REJECTED'")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_employee_cannot_mutate_and_admin_can_derive() -> None:
    async with (
        database_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        employee = replace(case.actor, role=MembershipRole.EMPLOYEE)
        case.app.dependency_overrides[get_authenticated_actor] = lambda: employee
        for method in ("POST", "PATCH"):
            response = await client.request(method, case.url, headers=headers(1))
            assert response.status_code == 403
        assert await case.connection.scalar(text("SELECT count(*) FROM team_requirement_sets")) == 0
        assert (
            await case.connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE outcome='REJECTED'")
            )
            == 2
        )
        admin = replace(case.actor, role=MembershipRole.ADMIN)
        case.app.dependency_overrides[get_authenticated_actor] = lambda: admin
        assert (await client.post(case.url, headers=headers())).status_code == 201
