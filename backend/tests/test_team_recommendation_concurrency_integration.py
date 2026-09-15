"""Independent production transactions for recommendation concurrency and rollback."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import create_database_engine
from app.main import create_app
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.assignment.adapters.recommendation_repository import (
    SqlAlchemyRecommendationRepository,
)
from tests.test_team_requirements_repository_integration import headers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]


@dataclass(frozen=True)
class ProductionCase:
    app: FastAPI
    actor: AuthenticatedActor
    project_id: UUID


@asynccontextmanager
async def production_case(settings: Settings | None = None) -> AsyncGenerator[ProductionCase]:
    settings = settings or Settings(environment="test")
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
    values = {
        "org": org,
        "member": member,
        "user": user,
        "project": project,
        "week": week,
        "skill": skill,
        "task": task,
        "person_skill": uuid4(),
        "capacity": uuid4(),
        "slug": str(org),
        "email": actor.email,
    }
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
        "INSERT INTO skills (id,organization_id,name,normalized_name,created_by_membership_id,"
        "updated_by_membership_id) VALUES (:skill,:org,'Research','research',:member,:member)",
        "INSERT INTO tasks (id,organization_id,project_id,project_week_id,title,status,"
        "required_skill_labels,estimated_effort_hours,created_by_membership_id,"
        "updated_by_membership_id) VALUES (:task,:org,:project,:week,'Discovery','TO_DO',"
        "'[\"Research\"]',8,:member,:member)",
        "INSERT INTO person_skills (id,organization_id,membership_id,skill_id,level,"
        "verified_by_membership_id,verified_at) "
        "VALUES (:person_skill,:org,:member,:skill,5,:member,now())",
        "INSERT INTO capacity_entries (id,organization_id,membership_id,kind,hours,"
        "effective_from,effective_to) "
        "VALUES (:capacity,:org,:member,'DEFAULT',40,'2026-01-01','2026-12-31')",
    )
    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement), values)
    app = create_app(settings)
    app.dependency_overrides[get_authenticated_actor] = lambda: actor
    try:
        yield ProductionCase(app, actor, project)
    finally:
        await app.state.database_engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(text("SET session_replication_role = 'replica'"))
            tables = (
                await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND column_name='organization_id'"
                    )
                )
            ).scalars()
            for table in tables:
                if table.replace("_", "").isalnum():
                    await connection.execute(
                        text(f'DELETE FROM "{table}" WHERE organization_id=:org'), {"org": org}
                    )
            await connection.execute(text("DELETE FROM organizations WHERE id=:org"), {"org": org})
            await connection.execute(text("DELETE FROM users WHERE id=:user"), {"user": user})
            await connection.execute(text("SET session_replication_role = 'origin'"))
        await engine.dispose()


@asynccontextmanager
async def isolated_migrated_database() -> AsyncGenerator[Settings]:
    base = Settings(environment="test")
    url = make_url(base.database_url)
    database_name = f"task11_{uuid4().hex}"
    admin_url = url.set(database="postgres").render_as_string(hide_password=False)
    database_url = url.set(database=database_name).render_as_string(hide_password=False)
    admin = create_database_engine(
        Settings(environment="test", database_url=admin_url)
    ).execution_options(isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    environment = {**os.environ, "APP_DATABASE_URL": database_url}
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        yield Settings(environment="test", database_url=database_url)
    finally:
        async with admin.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin.dispose()


async def create_recommendation(case: ProductionCase, client: AsyncClient) -> dict[str, object]:
    requirement_url = f"/api/v1/projects/{case.project_id}/team-requirements"
    created = await client.post(requirement_url, headers=headers())
    assert created.status_code == 201, created.text
    confirmed = await client.patch(requirement_url, headers=headers(1), json={"action": "confirm"})
    assert confirmed.status_code == 200, confirmed.text
    requirements = confirmed.json()
    response = await client.post(
        f"/api/v1/projects/{case.project_id}/team-recommendations",
        headers=headers(),
        json={
            "requirement_set_id": requirements["id"],
            "requirement_version": requirements["version"],
            "policy_version": "ranking-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_clean_0015_installs_provenance_triggers_and_allows_normal_create() -> None:
    async with isolated_migrated_database() as settings:
        engine = create_database_engine(settings)
        async with engine.connect() as connection:
            triggers = set(
                (
                    await connection.execute(
                        text(
                            "SELECT tgname FROM pg_trigger "
                            "WHERE NOT tgisinternal AND tgname LIKE '%_provenance'"
                        )
                    )
                ).scalars()
            )
        await engine.dispose()
        assert {
            "recommendations_provenance",
            "recommendation_versions_provenance",
            "candidate_scores_provenance",
            "recommendation_decisions_provenance",
            "project_team_memberships_provenance",
        } <= triggers
        async with (
            production_case(settings) as case,
            AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
        ):
            created = await create_recommendation(case, client)
            assert created["version"] == 1


@pytest.mark.asyncio
async def test_clean_0015_enforces_rls_tenant_fks_and_provenance_updates() -> None:
    async with (
        isolated_migrated_database() as settings,
        production_case(settings) as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        first = await create_recommendation(case, client)
        approved = await client.post(
            f"/api/v1/recommendations/{first['recommendation_id']}/approve",
            headers=headers(1),
            json={"action": "approve"},
        )
        assert approved.status_code == 200, approved.text
        project_two, week_two, task_two = uuid4(), uuid4(), uuid4()
        other_user, other_member = uuid4(), uuid4()
        org_b, user_b, member_b, project_b = (uuid4() for _ in range(4))
        engine = create_database_engine(settings)
        async with engine.begin() as connection:
            values = {
                "org": case.actor.organization_id,
                "manager": case.actor.membership_id,
                "project_two": project_two,
                "week_two": week_two,
                "task_two": task_two,
                "other_user": other_user,
                "other_member": other_member,
                "other_email": f"{other_user}@example.test",
                "org_b": org_b,
                "slug_b": str(org_b),
                "user_b": user_b,
                "member_b": member_b,
                "project_b": project_b,
                "email_b": f"{user_b}@example.test",
            }
            for statement in (
                "INSERT INTO projects (id,organization_id,name,created_by_membership_id,"
                "updated_by_membership_id) VALUES "
                "(:project_two,:org,'Other project',:manager,:manager)",
                "INSERT INTO project_weeks (id,organization_id,project_id,week_number,"
                "start_date,end_date,objective,created_by_membership_id,"
                "updated_by_membership_id) "
                "VALUES (:week_two,:org,:project_two,1,'2026-09-07','2026-09-13','Other',"
                ":manager,:manager)",
                "INSERT INTO tasks (id,organization_id,project_id,project_week_id,title,status,"
                "required_skill_labels,estimated_effort_hours,created_by_membership_id,"
                "updated_by_membership_id) VALUES "
                "(:task_two,:org,:project_two,:week_two,'Other','TO_DO','[\"Research\"]',8,"
                ":manager,:manager)",
                "INSERT INTO users "
                "(id,email_normalized,email_display,display_name,password_hash) "
                "VALUES (:other_user,:other_email,:other_email,'Other','unused')",
                "INSERT INTO memberships (id,organization_id,user_id,role) "
                "VALUES (:other_member,:org,:other_user,'EMPLOYEE')",
                "INSERT INTO organizations (id,slug,name) VALUES (:org_b,:slug_b,'Tenant B')",
                "INSERT INTO users "
                "(id,email_normalized,email_display,display_name,password_hash) "
                "VALUES (:user_b,:email_b,:email_b,'Tenant B','unused')",
                "INSERT INTO memberships (id,organization_id,user_id,role) "
                "VALUES (:member_b,:org_b,:user_b,'MANAGER')",
                "INSERT INTO projects (id,organization_id,name,created_by_membership_id,"
                "updated_by_membership_id) VALUES "
                "(:project_b,:org_b,'Tenant B project',:member_b,:member_b)",
            ):
                await connection.execute(text(statement), values)

        second = await create_recommendation(
            ProductionCase(case.app, case.actor, project_two), client
        )
        engine = create_database_engine(settings)
        async with engine.begin() as connection:
            first_version = await connection.scalar(
                text("SELECT id FROM recommendation_versions WHERE recommendation_id=:id"),
                {"id": first["recommendation_id"]},
            )
            second_row = (
                await connection.execute(
                    text(
                        "SELECT rv.requirement_set_id,rv.requirement_version,item.id "
                        "FROM recommendation_versions rv JOIN team_requirement_versions trv "
                        "ON trv.organization_id=rv.organization_id "
                        "AND trv.requirement_set_id=rv.requirement_set_id "
                        "AND trv.version=rv.requirement_version "
                        "JOIN team_requirement_items item "
                        "ON item.organization_id=trv.organization_id "
                        "AND item.requirement_version_id=trv.id "
                        "WHERE rv.recommendation_id=:id"
                    ),
                    {"id": second["recommendation_id"]},
                )
            ).one()
            decision = (
                await connection.execute(
                    text(
                        "SELECT id,recommendation_version_id FROM recommendation_decisions "
                        "WHERE recommendation_version_id=:version"
                    ),
                    {"version": first_version},
                )
            ).one()
            team_id = await connection.scalar(
                text(
                    "SELECT id FROM project_team_memberships "
                    "WHERE recommendation_version_id=:version"
                ),
                {"version": first_version},
            )
            base = {
                "org": case.actor.organization_id,
                "org_text": str(case.actor.organization_id),
                "recommendation": first["recommendation_id"],
                "version": first_version,
                "project": case.project_id,
                "project_two": project_two,
                "project_b": project_b,
                "org_b": org_b,
                "manager": case.actor.membership_id,
                "other_member": other_member,
                "decision": decision.id,
                "team": team_id,
                "set_two": second_row.requirement_set_id,
                "set_version_two": second_row.requirement_version,
                "item_two": second_row.id,
            }

            async def rejected(
                statement: str, sqlstate: str, constraint: str | None = None
            ) -> None:
                with pytest.raises(DBAPIError) as captured:
                    async with connection.begin_nested():
                        await connection.execute(text(statement), {**base, "id": uuid4()})
                assert getattr(captured.value.orig, "sqlstate", None) == sqlstate
                if constraint is not None:
                    driver_error = cast(Any, captured.value.orig)
                    assert driver_error.diag.constraint_name == constraint

            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            await connection.execute(text("SELECT set_config('app.organization_id','',true)"))
            await rejected(
                "INSERT INTO recommendations "
                "(id,organization_id,project_id,current_version,status) "
                "VALUES (:id,:org,:project,1,'PROPOSED')",
                "42501",
            )
            await connection.execute(
                text("SELECT set_config('app.organization_id',:org_text,true)"), base
            )
            await rejected(
                "INSERT INTO recommendations "
                "(id,organization_id,project_id,current_version,status) "
                "VALUES (:id,:org_b,:project_b,1,'PROPOSED')",
                "42501",
            )
            await connection.execute(text("RESET ROLE"))
            await rejected(
                "INSERT INTO recommendations "
                "(id,organization_id,project_id,current_version,status) "
                "VALUES (:id,:org,:project_b,1,'PROPOSED')",
                "23503",
                "fk_recommendations_organization_id_project_id_projects",
            )
            await rejected(
                "INSERT INTO recommendation_versions "
                "(id,organization_id,recommendation_id,version,requirement_set_id,"
                "requirement_version,policy_version,snapshot,input_snapshot,"
                "created_by_membership_id) VALUES "
                "(:id,:org,:recommendation,2,:set_two,:set_version_two,'ranking-v1',"
                "'{}','{}',:manager)",
                "23514",
            )
            await rejected(
                "INSERT INTO candidate_scores "
                "(id,organization_id,recommendation_version_id,requirement_id,membership_id,"
                "snapshot) VALUES (:id,:org,:version,:item_two,:manager,'{}')",
                "23514",
            )
            await rejected(
                "INSERT INTO recommendation_decisions "
                "(id,organization_id,recommendation_version_id,project_id,"
                "actor_membership_id,action) "
                "VALUES (:id,:org,:version,:project_two,:manager,'approve')",
                "23514",
            )
            await rejected(
                "INSERT INTO project_team_memberships "
                "(id,organization_id,project_id,membership_id,decision_id,"
                "recommendation_version_id,decision_action,active) "
                "VALUES (:id,:org,:project,:other_member,:decision,:version,'approve',true)",
                "23514",
            )
            await rejected(
                "UPDATE project_team_memberships SET membership_id=:other_member WHERE id=:team",
                "23514",
            )
            await rejected(
                "UPDATE recommendations SET project_id=:project_two WHERE id=:recommendation",
                "23514",
            )
            changed = await connection.execute(
                text("UPDATE project_team_memberships SET active=false WHERE id=:team"), base
            )
            assert changed.rowcount == 1
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_approvals_apply_exactly_once_across_independent_transactions() -> None:
    async with production_case() as case:
        async with AsyncClient(
            transport=ASGITransport(app=case.app), base_url="http://test"
        ) as client:
            recommendation = await create_recommendation(case, client)
            url = f"/api/v1/recommendations/{recommendation['recommendation_id']}/approve"
            first, second = await asyncio.gather(
                client.post(url, headers=headers(1), json={"action": "approve"}),
                client.post(url, headers=headers(1), json={"action": "approve"}),
            )
        assert sorted((first.status_code, second.status_code)) == [200, 409]
        engine = create_database_engine(Settings(environment="test"))
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM recommendation_decisions "
                        "WHERE organization_id=:organization_id AND action='approve'"
                    ),
                    {"organization_id": case.actor.organization_id},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM project_team_memberships "
                        "WHERE organization_id=:organization_id"
                    ),
                    {"organization_id": case.actor.organization_id},
                )
                == 1
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_approve_and_revise_preserve_one_exact_version_winner() -> None:
    async with (
        production_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        recommendation = await create_recommendation(case, client)
        root = f"/api/v1/recommendations/{recommendation['recommendation_id']}"
        approved, revised = await asyncio.gather(
            client.post(root + "/approve", headers=headers(1), json={"action": "approve"}),
            client.patch(root, headers=headers(1), json={"overrides": []}),
        )
        assert sorted((approved.status_code, revised.status_code))[0] == 200
        assert sum(response.status_code == 200 for response in (approved, revised)) == 1
        assert next(
            response.status_code for response in (approved, revised) if response.status_code != 200
        ) in {409, 412}

        current = await client.get(root)
        assert current.status_code == 200
        if approved.status_code == 200:
            assert current.json()["status"] == "APPROVED"
            assert current.json()["version"] == 1
        else:
            assert current.json()["status"] == "PROPOSED"
            assert current.json()["version"] == 2


@pytest.mark.asyncio
async def test_concurrent_eligibility_change_has_a_coherent_serial_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with (
        production_case() as case,
        AsyncClient(transport=ASGITransport(app=case.app), base_url="http://test") as client,
    ):
        recommendation = await create_recommendation(case, client)
        entered_preview = asyncio.Event()
        release_preview = asyncio.Event()
        original_preview = vars(SqlAlchemyRecommendationRepository)["_preview"]

        async def paused_preview(
            repository: SqlAlchemyRecommendationRepository,
            actor: AuthenticatedActor,
            project_id: UUID,
        ):  # type: ignore[no-untyped-def]
            entered_preview.set()
            await release_preview.wait()
            return await original_preview(repository, actor, project_id)

        monkeypatch.setattr(SqlAlchemyRecommendationRepository, "_preview", paused_preview)
        url = f"/api/v1/recommendations/{recommendation['recommendation_id']}/approve"
        approval_task = asyncio.create_task(
            client.post(url, headers=headers(1), json={"action": "approve"})
        )
        await entered_preview.wait()
        engine = create_database_engine(Settings(environment="test"))
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE capacity_entries SET hours=0 "
                    "WHERE organization_id=:organization_id AND membership_id=:membership_id"
                ),
                {
                    "organization_id": case.actor.organization_id,
                    "membership_id": case.actor.membership_id,
                },
            )
        release_preview.set()
        approval = await approval_task
        monkeypatch.setattr(SqlAlchemyRecommendationRepository, "_preview", original_preview)
        assert approval.status_code in {200, 409}
        current = await client.get(f"/api/v1/recommendations/{recommendation['recommendation_id']}")
        assert current.status_code == 200
        async with engine.connect() as connection:
            team_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM project_team_memberships "
                    "WHERE organization_id=:organization_id"
                ),
                {"organization_id": case.actor.organization_id},
            )
        assert team_count == (1 if approval.status_code == 200 else 0)
        assert current.json()["status"] == ("APPROVED" if approval.status_code == 200 else "STALE")
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["flush", "commit"])
async def test_commit_failure_rolls_back_membership_decision_audit_outbox_and_replay(
    monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    async with production_case() as case:
        async with AsyncClient(
            transport=ASGITransport(app=case.app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            recommendation = await create_recommendation(case, client)
            original_commit = AsyncSession.commit
            original_flush = AsyncSession.flush

            async def fail_commit(_session: AsyncSession) -> None:
                raise RuntimeError("injected commit failure")

            async def fail_final_flush(
                session: AsyncSession, objects: object | None = None
            ) -> None:
                if any(item.__class__.__name__ == "AuditEventModel" for item in session.new):
                    raise RuntimeError("injected flush failure")
                await original_flush(session, objects)  # type: ignore[arg-type]

            if boundary == "commit":
                monkeypatch.setattr(AsyncSession, "commit", fail_commit)
            else:
                monkeypatch.setattr(AsyncSession, "flush", fail_final_flush)
            decision_headers = headers(1)
            with pytest.raises(RuntimeError, match=f"injected {boundary} failure"):
                await client.post(
                    f"/api/v1/recommendations/{recommendation['recommendation_id']}/approve",
                    headers=decision_headers,
                    json={"action": "approve"},
                )
            monkeypatch.setattr(AsyncSession, "commit", original_commit)
            monkeypatch.setattr(AsyncSession, "flush", original_flush)

        engine = create_database_engine(Settings(environment="test"))
        async with engine.connect() as connection:
            for table in ("project_team_memberships", "recommendation_decisions"):
                assert (
                    await connection.scalar(
                        text(
                            f"SELECT count(*) FROM {table} WHERE organization_id=:organization_id"
                        ),
                        {"organization_id": case.actor.organization_id},
                    )
                    == 0
                )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM audit_events WHERE organization_id=:organization_id "
                        "AND action='team_recommendation.approved'"
                    ),
                    {"organization_id": case.actor.organization_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM outbox_events WHERE organization_id=:organization_id "
                        "AND event_type='team_recommendation.approved.v1'"
                    ),
                    {"organization_id": case.actor.organization_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM idempotency_records "
                        "WHERE organization_id=:organization_id "
                        "AND operation='team_recommendation.DecideRecommendationCommand' "
                        "AND idempotency_key=:idempotency_key"
                    ),
                    {
                        "organization_id": case.actor.organization_id,
                        "idempotency_key": decision_headers["Idempotency-Key"],
                    },
                )
                == 0
            )
            root = (
                await connection.execute(
                    text(
                        "SELECT status,current_version FROM recommendations "
                        "WHERE organization_id=:organization_id"
                    ),
                    {"organization_id": case.actor.organization_id},
                )
            ).one()
            assert root == ("PROPOSED", 1)
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM recommendation_versions "
                        "WHERE organization_id=:organization_id"
                    ),
                    {"organization_id": case.actor.organization_id},
                )
                == 1
            )
        await engine.dispose()

        async with AsyncClient(
            transport=ASGITransport(app=case.app), base_url="http://test"
        ) as recovery_client:
            url = f"/api/v1/recommendations/{recommendation['recommendation_id']}/approve"
            recovered = await recovery_client.post(
                url, headers=decision_headers, json={"action": "approve"}
            )
            replayed = await recovery_client.post(
                url, headers=decision_headers, json={"action": "approve"}
            )
            assert recovered.status_code == 200, recovered.text
            assert replayed.json() == recovered.json()
            assert replayed.headers["Idempotency-Replayed"] == "true"
