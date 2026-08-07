from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.database import create_database_engine
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.adapters.transaction import (
    PostgreSQLPlanningRunTransaction,
    PostgreSQLPlanningRunTransactionFactory,
)
from app.modules.planning_runs.application.job_service import JobService
from app.modules.planning_runs.domain.models import PlanningRunDomainError, WorkflowJobStatus


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_cannot_claim_tenant_outside_configured_scope() -> None:
    # 1. Test the service boundary
    engine = create_database_engine(Settings(environment="test"))
    db_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    factory = PostgreSQLPlanningRunTransactionFactory(db_session_factory)
    allowed_tenant = uuid4()
    disallowed_tenant = uuid4()

    service = JobService(
        transaction_factory=factory,
        handlers={},
        organization_scopes={allowed_tenant},
    )

    with pytest.raises(PlanningRunDomainError, match="Worker organization scope violation"):
        await service.run_once("test-worker", disallowed_tenant)

    # 2. Test the RLS boundary with AuthenticatedActor
    actor = AuthenticatedActor(
        user_id=uuid4(),
        email="test@example.com",
        display_name="Test Worker",
        membership_id=uuid4(),
        organization_id=allowed_tenant,
        organization_name="Test",
        role=MembershipRole.ADMIN,
    )

    txn = factory(actor)
    assert isinstance(txn, PostgreSQLPlanningRunTransaction)
    async with txn:
        result = await txn.session.execute(text("SELECT current_setting('app.organization_id')"))
        db_tenant = result.scalar()
        assert db_tenant == str(allowed_tenant)

    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_rls_tenant_context_applied_with_uuid() -> None:
    engine = create_database_engine(Settings(environment="test"))
    db_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    factory = PostgreSQLPlanningRunTransactionFactory(db_session_factory)
    tenant_id = uuid4()

    txn = factory(tenant_id)
    assert isinstance(txn, PostgreSQLPlanningRunTransaction)
    async with txn:
        result = await txn.session.execute(text("SELECT current_setting('app.organization_id')"))
        db_tenant = result.scalar()
        assert db_tenant == str(tenant_id)

        # Check membership_id is null/unset
        result_mem = await txn.session.execute(
            text("SELECT current_setting('app.membership_id', true)")
        )
        db_mem = result_mem.scalar()
        assert db_mem is None or db_mem == ""

    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_job_lease_and_expired_reclaim() -> None:
    engine = create_database_engine(Settings(environment="test"))
    db_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    factory = PostgreSQLPlanningRunTransactionFactory(db_session_factory)
    tenant_id = uuid4()

    # Create a job via raw transaction to test repository locking logic
    user_id = uuid4()
    member_id = uuid4()
    project_id = uuid4()
    run_id = uuid4()
    job_id = uuid4()
    now = datetime.now(UTC)

    async with engine.connect() as conn:
        transaction = await conn.begin()
        await conn.execute(
            text(
                "INSERT INTO organizations (id, name, slug, created_at, updated_at) "
                "VALUES (:id, 'Test Org', :slug, :now, :now) ON CONFLICT DO NOTHING"
            ),
            {"id": tenant_id, "slug": f"test-org-{uuid4().hex[:8]}", "now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO users "
                "(id, email_normalized, email_display, display_name, password_hash) "
                "VALUES (:id, :email, :email, 'Test User', 'hash')"
            ),
            {"id": user_id, "email": f"{user_id.hex}@example.test"},
        )
        await conn.execute(
            text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :org, :user, 'MANAGER')"
            ),
            {"id": member_id, "org": tenant_id, "user": user_id},
        )
        await conn.execute(
            text(
                "INSERT INTO projects "
                "(id, organization_id, name, description, "
                "created_by_membership_id, updated_by_membership_id, version, "
                "created_at, updated_at) "
                "VALUES (:id, :org_id, 'Test Project', 'Desc', :mem_id, :mem_id, 1, :now, :now)"
            ),
            {"id": project_id, "org_id": tenant_id, "mem_id": member_id, "now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO workflow_runs "
                "(id, organization_id, project_id, requested_by_membership_id, "
                "workflow_name, workflow_version, verifier_version, "
                "input_goal_text, status, created_at, updated_at) "
                "VALUES ("
                ":id, :org_id, :project_id, :mem_id, 'test_wf', "
                "'1.0', '1.0', 'Test Goal', 'QUEUED', :now, :now"
                ")"
            ),
            {
                "id": run_id,
                "org_id": tenant_id,
                "project_id": project_id,
                "mem_id": member_id,
                "now": now,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO workflow_jobs "
                "(id, workflow_run_id, organization_id, job_type, status, "
                "attempt_count, max_attempts, available_at, payload, created_at, updated_at) "
                "VALUES (:id, :run_id, :org_id, 'test_job', 'QUEUED', 0, 3, :now, '{}', :now, :now)"
            ),
            {"id": job_id, "run_id": run_id, "org_id": tenant_id, "now": now},
        )
        await transaction.commit()

    # Worker 1 claims job
    txn1 = factory(tenant_id)
    assert isinstance(txn1, PostgreSQLPlanningRunTransaction)
    async with txn1:
        job1 = await txn1.repository.claim_job(
            organization_id=tenant_id,
            worker_id="worker-1",
            now=now,
            lease_until=now + timedelta(seconds=60),
        )
        assert job1 is not None
        assert job1.id == job_id
        assert job1.status == WorkflowJobStatus.RUNNING
        assert job1.locked_by_worker_id == "worker-1"
        await txn1.commit()

    # Worker 2 attempts concurrent claim while lease active -> should return None
    txn2 = factory(tenant_id)
    assert isinstance(txn2, PostgreSQLPlanningRunTransaction)
    async with txn2:
        job2 = await txn2.repository.claim_job(
            organization_id=tenant_id,
            worker_id="worker-2",
            now=now + timedelta(seconds=10),
            lease_until=now + timedelta(seconds=70),
        )
        assert job2 is None
        await txn2.commit()

    # Worker 3 claims job after lease expires (past now + 60s) -> should reclaim job
    expired_now = now + timedelta(seconds=61)
    txn3 = factory(tenant_id)
    assert isinstance(txn3, PostgreSQLPlanningRunTransaction)
    async with txn3:
        job3 = await txn3.repository.claim_job(
            organization_id=tenant_id,
            worker_id="worker-3",
            now=expired_now,
            lease_until=expired_now + timedelta(seconds=60),
        )
        assert job3 is not None
        assert job3.id == job_id
        assert job3.locked_by_worker_id == "worker-3"
        await txn3.commit()

    await engine.dispose()
