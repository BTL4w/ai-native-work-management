"""Integration tests for PostgreSQLPlanningRunRepository and planning runs persistence."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import create_database_engine
from app.modules.identity.domain.auth import AuthenticatedActor, MembershipRole
from app.modules.organization.adapters import database_models as _org_models
from app.modules.planning_runs.adapters.repository import PostgreSQLPlanningRunRepository
from app.modules.planning_runs.adapters.transaction import (
    PostgreSQLPlanningRunTransaction,
    PostgreSQLPlanningRunTransactionFactory,
)
from app.modules.planning_runs.domain.models import (
    Approval,
    ApprovalStatus,
    Proposal,
    ProposalStatus,
    ProposalVersion,
    WorkflowJob,
    WorkflowJobStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.modules.work.adapters import database_models as _work_models

_MODELS = (_org_models, _work_models)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]


def make_actor(
    org_id: UUID,
    role: MembershipRole = MembershipRole.MANAGER,
    membership_id: UUID | None = None,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="test@example.com",
        display_name="Test User",
        membership_id=membership_id or uuid4(),
        organization_id=org_id,
        organization_name="Test Org",
        role=role,
    )


@pytest.mark.asyncio
async def test_workflow_run_and_job_atomic_creation() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_id, user_id, member_id, project_id, run_id, job_id = (uuid4() for _ in range(6))
    actor = make_actor(org_id, membership_id=member_id)

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, 'Org Test')"),
                {"id": org_id, "slug": f"org-test-{org_id.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'User Test', 'hash')"
                ),
                {"id": user_id, "email": f"{user_id.hex}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, 'MANAGER')"
                ),
                {"id": member_id, "org": org_id, "user": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, "
                    "created_by_membership_id, updated_by_membership_id) "
                    "VALUES (:id, :org, 'Project Test', :member, :member)"
                ),
                {"id": project_id, "org": org_id, "member": member_id},
            )

            await connection.execute(
                text("SELECT set_config('app.organization_id', :val, true)"),
                {"val": str(org_id)},
            )

            session = AsyncSession(bind=connection, expire_on_commit=False)
            repo = PostgreSQLPlanningRunRepository(session)

            run = WorkflowRun.create(
                id=run_id,
                organization_id=org_id,
                project_id=project_id,
                requested_by_membership_id=member_id,
                workflow_name="planning",
                workflow_version="v1.0",
                verifier_version="planning-verifier-v1",
                input_goal_text="Test goal text",
            )
            job = WorkflowJob(
                id=job_id,
                organization_id=org_id,
                workflow_run_id=run_id,
                job_type="planning.start",
                status=WorkflowJobStatus.QUEUED,
                payload={"goal": "Test goal text"},
            )

            await repo.create_workflow_run(run=run, job=job)

            fetched_run = await repo.get_workflow_run(actor=actor, run_id=run_id)
            assert fetched_run is not None
            assert fetched_run.id == run_id
            assert fetched_run.status == WorkflowRunStatus.QUEUED
            assert fetched_run.input_goal_text == "Test goal text"
            assert fetched_run.verifier_version == "planning-verifier-v1"

            now = datetime.now(UTC)
            lease_until = now + timedelta(minutes=5)
            claimed = await repo.claim_job(worker_id="worker-1", now=now, lease_until=lease_until)
            assert claimed is not None
            assert claimed.id == job_id
            assert claimed.locked_by_worker_id == "worker-1"

            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_proposal_versioning_and_approval_superseding() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_id, user_id, member_id, project_id, run_id, proposal_id, version_id, approval_id = (
        uuid4() for _ in range(8)
    )
    actor = make_actor(org_id, membership_id=member_id)

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, 'Org Test')"),
                {"id": org_id, "slug": f"org-prop-{org_id.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'User Prop', 'hash')"
                ),
                {"id": user_id, "email": f"{user_id.hex}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, 'MANAGER')"
                ),
                {"id": member_id, "org": org_id, "user": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, "
                    "created_by_membership_id, updated_by_membership_id) "
                    "VALUES (:id, :org, 'Project Prop', :member, :member)"
                ),
                {"id": project_id, "org": org_id, "member": member_id},
            )

            await connection.execute(
                text("SELECT set_config('app.organization_id', :val, true)"),
                {"val": str(org_id)},
            )

            session = AsyncSession(bind=connection, expire_on_commit=False)
            repo = PostgreSQLPlanningRunRepository(session)

            run = WorkflowRun.create(
                id=run_id,
                organization_id=org_id,
                project_id=project_id,
                requested_by_membership_id=member_id,
                workflow_name="planning",
                workflow_version="v1.0",
                verifier_version="planning-verifier-v1",
                input_goal_text="Proposal goal",
            )
            await repo.create_workflow_run(run=run)

            proposal = Proposal.create(
                id=proposal_id,
                organization_id=org_id,
                workflow_run_id=run_id,
                current_version_number=1,
            )
            initial_ver = ProposalVersion(
                id=version_id,
                organization_id=org_id,
                proposal_id=proposal_id,
                version_number=1,
                created_by_membership_id=member_id,
                content={"tasks": [{"title": "Task 1"}]},
                assumptions=[{"text": "Assumption 1"}],
            )

            await repo.create_proposal(proposal=proposal, initial_version=initial_ver)

            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            with pytest.raises(DBAPIError, match="approval must be inserted as PENDING"):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO approvals "
                            "(id, organization_id, proposal_id, proposal_version_number, status, "
                            "decided_by_membership_id, decided_at, version) VALUES "
                            "(:id, :org, :proposal, 1, 'APPROVED', :member, now(), 2)"
                        ),
                        {
                            "id": uuid4(),
                            "org": org_id,
                            "proposal": proposal_id,
                            "member": member_id,
                        },
                    )
            await connection.execute(text("RESET ROLE"))

            approval = Approval.create(
                id=approval_id,
                organization_id=org_id,
                proposal_id=proposal_id,
                proposal_version_number=1,
            )
            await repo.create_approval(approval=approval)

            await connection.execute(text("SET LOCAL ROLE app_runtime"))
            await connection.execute(
                text("SELECT set_config('app.membership_id', :member, true)"),
                {"member": str(uuid4())},
            )
            with pytest.raises(DBAPIError, match="authenticated membership"):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "UPDATE approvals SET status = 'APPROVED', "
                            "decided_by_membership_id = :member, decided_at = now(), "
                            "version = 2 WHERE id = :id"
                        ),
                        {"member": member_id, "id": approval_id},
                    )
            await connection.execute(text("RESET ROLE"))

            ready_prop = proposal.mark_ready(approval_id=approval_id)
            await repo.update_proposal(actor=actor, proposal=ready_prop)

            v2_id = uuid4()
            ver2 = ProposalVersion(
                id=v2_id,
                organization_id=org_id,
                proposal_id=proposal_id,
                version_number=2,
                created_by_membership_id=member_id,
                content={"tasks": [{"title": "Task 1 Updated"}]},
                assumptions=[],
            )
            edited_prop = ready_prop.edit()
            superseded_approval = approval.mark_superseded()
            employee = make_actor(
                org_id,
                role=MembershipRole.EMPLOYEE,
                membership_id=member_id,
            )
            with pytest.raises(PermissionError, match="Manager"):
                await repo.edit_proposal(
                    actor=employee,
                    proposal=edited_prop,
                    version=ver2,
                    superseded_approval=superseded_approval,
                )
            forged_version = ProposalVersion(
                id=ver2.id,
                organization_id=ver2.organization_id,
                proposal_id=ver2.proposal_id,
                version_number=ver2.version_number,
                created_by_membership_id=uuid4(),
                content=ver2.content,
                assumptions=ver2.assumptions,
            )
            with pytest.raises(PermissionError, match="authenticated actor"):
                await repo.edit_proposal(
                    actor=actor,
                    proposal=edited_prop,
                    version=forged_version,
                    superseded_approval=superseded_approval,
                )
            await repo.edit_proposal(
                actor=actor,
                proposal=edited_prop,
                version=ver2,
                superseded_approval=superseded_approval,
            )

            # Once proposal is edited (moved to DRAFT), trying to approve the old approval fails
            stale_decision = approval.decide_approve(decided_by=member_id)
            stale_proposal_decision = ready_prop.mark_approved()
            with pytest.raises(RuntimeError, match="proposal is not READY"):
                await repo.decide_approval(
                    actor=actor,
                    approval=stale_decision,
                    proposal=stale_proposal_decision,
                )

            fetched_approval = await repo.get_approval(actor=actor, approval_id=approval_id)
            assert fetched_approval is not None
            assert fetched_approval.status == ApprovalStatus.SUPERSEDED
            assert fetched_approval.version == 2

            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approval_optimistic_concurrency_failure_and_version_hydration() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_id, user_id, member_id, project_id, run_id, proposal_id, version_id, approval_id = (
        uuid4() for _ in range(8)
    )
    actor = make_actor(org_id, membership_id=member_id)

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, 'Org Test')"),
                {"id": org_id, "slug": f"org-conc-{org_id.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'User Conc', 'hash')"
                ),
                {"id": user_id, "email": f"{user_id.hex}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, 'MANAGER')"
                ),
                {"id": member_id, "org": org_id, "user": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, "
                    "created_by_membership_id, updated_by_membership_id) "
                    "VALUES (:id, :org, 'Project Conc', :member, :member)"
                ),
                {"id": project_id, "org": org_id, "member": member_id},
            )

            await connection.execute(
                text("SELECT set_config('app.organization_id', :val, true)"),
                {"val": str(org_id)},
            )

            session = AsyncSession(bind=connection, expire_on_commit=False)
            repo = PostgreSQLPlanningRunRepository(session)

            run = WorkflowRun.create(
                id=run_id,
                organization_id=org_id,
                project_id=project_id,
                requested_by_membership_id=member_id,
                workflow_name="planning",
                workflow_version="v1.0",
                verifier_version="planning-verifier-v1",
                input_goal_text="Conc goal",
            )
            await repo.create_workflow_run(run=run)

            proposal = Proposal.create(
                id=proposal_id,
                organization_id=org_id,
                workflow_run_id=run_id,
            )
            initial_ver = ProposalVersion(
                id=version_id,
                organization_id=org_id,
                proposal_id=proposal_id,
                version_number=1,
                created_by_membership_id=member_id,
                content={"tasks": []},
                assumptions=[],
            )
            await repo.create_proposal(proposal=proposal, initial_version=initial_ver)

            approval = Approval.create(
                id=approval_id,
                organization_id=org_id,
                proposal_id=proposal_id,
                proposal_version_number=1,
            )
            await repo.create_approval(approval=approval)

            ready_proposal = proposal.mark_ready(approval_id=approval_id)
            await repo.update_proposal(actor=actor, proposal=ready_proposal)

            spoofed = approval.decide_approve(decided_by=uuid4(), decision_reason="Forged")
            with pytest.raises(PermissionError, match="authenticated actor"):
                await repo.decide_approval(
                    actor=actor,
                    approval=spoofed,
                    proposal=ready_proposal.mark_approved(),
                )

            employee = make_actor(
                org_id,
                role=MembershipRole.EMPLOYEE,
                membership_id=member_id,
            )
            employee_decision = approval.decide_approve(decided_by=member_id)
            with pytest.raises(PermissionError, match="Manager"):
                await repo.decide_approval(
                    actor=employee,
                    approval=employee_decision,
                    proposal=ready_proposal.mark_approved(),
                )

            # First decision succeeds and bumps version to 2
            decided = approval.decide_approve(decided_by=member_id, decision_reason="OK")
            approved_proposal = ready_proposal.mark_approved()
            assert decided.version == 2
            await repo.decide_approval(
                actor=actor,
                approval=decided,
                proposal=approved_proposal,
            )

            # Hydration check: get_approval returns approval with version 2
            reloaded = await repo.get_approval(actor=actor, approval_id=approval_id)
            assert reloaded is not None
            assert reloaded.version == 2
            assert reloaded.status == ApprovalStatus.APPROVED

            reloaded_proposal = await repo.get_proposal(actor=actor, proposal_id=proposal_id)
            assert reloaded_proposal is not None
            assert reloaded_proposal.status == ProposalStatus.APPROVED
            assert reloaded_proposal.version == approved_proposal.version

            with pytest.raises(DBAPIError, match="terminal approval"):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "UPDATE approvals SET status = 'REJECTED', version = version + 1 "
                            "WHERE id = :id"
                        ),
                        {"id": approval_id},
                    )

            # A proposal edit made from the pre-decision READY snapshot is stale.
            stale_edit = ready_proposal.edit()
            with pytest.raises(RuntimeError, match="concurrent mutation"):
                await repo.update_proposal(actor=actor, proposal=stale_edit)

            # A concurrent attempt trying to update from stale version 1 fails
            stale_decision = approval.decide_reject(decided_by=member_id, decision_reason="Stale")
            rejected_proposal = ready_proposal.mark_rejected()
            with pytest.raises(
                RuntimeError,
                match=r"proposal is not READY|optimistic concurrency",
            ):
                await repo.decide_approval(
                    actor=actor,
                    approval=stale_decision,
                    proposal=rejected_proposal,
                )

            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_edit_waits_for_decision_lock_and_then_rejects_stale_snapshot() -> None:
    engine = create_database_engine(Settings(environment="test"))
    org_id, user_id, member_id, project_id, run_id, proposal_id, version_id, approval_id = (
        uuid4() for _ in range(8)
    )
    actor = make_actor(org_id, membership_id=member_id)

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, 'Race Org')"),
                {"id": org_id, "slug": f"race-{org_id.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'Race User', 'hash')"
                ),
                {"id": user_id, "email": f"{user_id.hex}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, 'MANAGER')"
                ),
                {"id": member_id, "org": org_id, "user": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, "
                    "created_by_membership_id, updated_by_membership_id) "
                    "VALUES (:id, :org, 'Race Project', :member, :member)"
                ),
                {"id": project_id, "org": org_id, "member": member_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(id, organization_id, project_id, requested_by_membership_id, status, "
                    "workflow_name, workflow_version, verifier_version, input_goal_text) "
                    "VALUES (:id, :org, :project, :member, 'QUEUED', 'planning', 'v1', "
                    "'verifier-v1', 'Race goal')"
                ),
                {"id": run_id, "org": org_id, "project": project_id, "member": member_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO proposals "
                    "(id, organization_id, workflow_run_id, status, current_version_number) "
                    "VALUES (:id, :org, :run, 'DRAFT', 1)"
                ),
                {"id": proposal_id, "org": org_id, "run": run_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO proposal_versions "
                    "(id, organization_id, proposal_id, version_number, "
                    "created_by_membership_id, content, assumptions) "
                    "VALUES (:id, :org, :proposal, 1, :member, '{}', '[]')"
                ),
                {
                    "id": version_id,
                    "org": org_id,
                    "proposal": proposal_id,
                    "member": member_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO approvals "
                    "(id, organization_id, proposal_id, proposal_version_number) "
                    "VALUES (:id, :org, :proposal, 1)"
                ),
                {"id": approval_id, "org": org_id, "proposal": proposal_id},
            )
            await connection.execute(
                text(
                    "UPDATE proposals SET status = 'READY', approval_id = :approval, version = 2 "
                    "WHERE id = :proposal"
                ),
                {"approval": approval_id, "proposal": proposal_id},
            )

        async with (
            AsyncSession(engine, expire_on_commit=False) as session_a,
            AsyncSession(engine, expire_on_commit=False) as session_b,
        ):
            repo_a = PostgreSQLPlanningRunRepository(session_a)
            repo_b = PostgreSQLPlanningRunRepository(session_b)
            await session_a.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org_id)},
            )
            await session_b.execute(
                text("SELECT set_config('app.organization_id', :org, true)"),
                {"org": str(org_id)},
            )
            ready = await repo_a.get_proposal(actor=actor, proposal_id=proposal_id)
            pending = await repo_a.get_approval(actor=actor, approval_id=approval_id)
            assert ready is not None
            assert pending is not None

            await session_a.execute(
                text("SELECT id FROM proposals WHERE id = :id FOR UPDATE"),
                {"id": proposal_id},
            )
            edited = ready.edit()
            superseded = pending.mark_superseded()
            version_two = ProposalVersion(
                id=uuid4(),
                organization_id=org_id,
                proposal_id=proposal_id,
                version_number=2,
                created_by_membership_id=member_id,
                content={"edited": True},
                assumptions=[],
            )
            edit_task = asyncio.create_task(
                repo_b.edit_proposal(
                    actor=actor,
                    proposal=edited,
                    version=version_two,
                    superseded_approval=superseded,
                )
            )
            done, _ = await asyncio.wait({edit_task}, timeout=0.1)
            assert not done

            await repo_a.decide_approval(
                actor=actor,
                approval=pending.decide_approve(decided_by=member_id),
                proposal=ready.mark_approved(),
            )
            await session_a.commit()

            with pytest.raises(RuntimeError, match="concurrent mutation"):
                await edit_task
            await session_b.rollback()
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM workflow_runs WHERE organization_id = :org"), {"org": org_id}
            )
            await connection.execute(
                text("DELETE FROM projects WHERE organization_id = :org"), {"org": org_id}
            )
            await connection.execute(
                text("DELETE FROM memberships WHERE organization_id = :org"), {"org": org_id}
            )
            await connection.execute(
                text("DELETE FROM organizations WHERE id = :org"), {"org": org_id}
            )
            await connection.execute(text("DELETE FROM users WHERE id = :user"), {"user": user_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_planning_run_transaction_context_manager_enforces_app_runtime_role() -> None:
    engine = create_database_engine(Settings(environment="test"))
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    factory = PostgreSQLPlanningRunTransactionFactory(session_factory)

    org_a, org_b, user_a, user_b, member_a, member_b, project_a, project_b, run_a, run_b = (
        uuid4() for _ in range(10)
    )
    actor_a = make_actor(org_a, membership_id=member_a)

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) VALUES "
                    "(:a, :sa, 'A'), (:b, :sb, 'B')"
                ),
                {
                    "a": org_a,
                    "sa": f"tx-a-{org_a.hex}",
                    "b": org_b,
                    "sb": f"tx-b-{org_b.hex}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) VALUES "
                    "(:a, :email_a, :email_a, 'User A', 'hash'), "
                    "(:b, :email_b, :email_b, 'User B', 'hash')"
                ),
                {
                    "a": user_a,
                    "email_a": f"{user_a.hex}@example.test",
                    "b": user_b,
                    "email_b": f"{user_b.hex}@example.test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) VALUES "
                    "(:member_a, :org_a, :user_a, 'MANAGER'), "
                    "(:member_b, :org_b, :user_b, 'MANAGER')"
                ),
                {
                    "member_a": member_a,
                    "org_a": org_a,
                    "user_a": user_a,
                    "member_b": member_b,
                    "org_b": org_b,
                    "user_b": user_b,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, created_by_membership_id, "
                    "updated_by_membership_id) VALUES "
                    "(:project_a, :org_a, 'Project A', :member_a, :member_a), "
                    "(:project_b, :org_b, 'Project B', :member_b, :member_b)"
                ),
                {
                    "project_a": project_a,
                    "org_a": org_a,
                    "member_a": member_a,
                    "project_b": project_b,
                    "org_b": org_b,
                    "member_b": member_b,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(id, organization_id, project_id, requested_by_membership_id, status, "
                    "workflow_name, workflow_version, verifier_version, input_goal_text) VALUES "
                    "(:run_a, :org_a, :project_a, :member_a, 'QUEUED', 'planning', 'v1.0', "
                    "'planning-verifier-v1', 'Goal A'), "
                    "(:run_b, :org_b, :project_b, :member_b, 'QUEUED', 'planning', 'v1.0', "
                    "'planning-verifier-v1', 'Goal B')"
                ),
                {
                    "run_a": run_a,
                    "org_a": org_a,
                    "project_a": project_a,
                    "member_a": member_a,
                    "run_b": run_b,
                    "org_b": org_b,
                    "project_b": project_b,
                    "member_b": member_b,
                },
            )
            with pytest.raises(DBAPIError, match="ck_workflow_runs_verifier_version"):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO workflow_runs "
                            "(id, organization_id, project_id, requested_by_membership_id, status, "
                            "workflow_name, workflow_version, verifier_version, input_goal_text) "
                            "VALUES (:id, :org, :project, :member, 'QUEUED', 'planning', 'v1', "
                            "E'\\t\\n', 'invalid verifier')"
                        ),
                        {
                            "id": uuid4(),
                            "org": org_a,
                            "project": project_a,
                            "member": member_a,
                        },
                    )

        tx = factory(actor_a)
        assert isinstance(tx, PostgreSQLPlanningRunTransaction)
        with pytest.raises(RuntimeError, match="outside an active transaction"):
            _ = tx.repository
        with pytest.raises(DBAPIError, match="row-level security"):
            async with tx:
                session = tx._session  # type: ignore[reportPrivateUsage]
                assert await session.scalar(text("SELECT current_user")) == "app_runtime"
                assert await session.scalar(
                    text("SELECT current_setting('app.organization_id')")
                ) == str(org_a)
                assert await session.scalar(
                    text("SELECT current_setting('app.membership_id')")
                ) == str(member_a)

                hidden = await tx.repository.get_workflow_run(actor=actor_a, run_id=run_b)
                assert hidden is None

                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(
                            text(
                                "UPDATE workflow_runs SET verifier_version = 'tampered' "
                                "WHERE id = :id"
                            ),
                            {"id": run_a},
                        )

                foreign_run = WorkflowRun.create(
                    organization_id=org_b,
                    project_id=project_b,
                    requested_by_membership_id=member_b,
                    workflow_name="planning",
                    workflow_version="v1.0",
                    verifier_version="planning-verifier-v1",
                    input_goal_text="Forbidden cross-tenant run",
                )
                await tx.repository.create_workflow_run(run=foreign_run)

        committed_tx = factory(actor_a)
        with pytest.raises(RuntimeError, match="outside an active transaction"):
            _ = committed_tx.repository
        async with committed_tx:
            retained_repository = committed_tx.repository
            await committed_tx.commit()
            with pytest.raises(InvalidRequestError, match="closed transaction"):
                await retained_repository.get_workflow_run(actor=actor_a, run_id=run_b)
            with pytest.raises(RuntimeError, match="outside an active transaction"):
                _ = committed_tx.repository
        with pytest.raises(RuntimeError, match="outside an active transaction"):
            _ = committed_tx.repository
        with pytest.raises(InvalidRequestError, match="permanently closed"):
            await retained_repository.get_workflow_run(actor=actor_a, run_id=run_a)
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM workflow_runs WHERE organization_id IN (:org_a, :org_b)"),
                {"org_a": org_a, "org_b": org_b},
            )
            await connection.execute(
                text("DELETE FROM projects WHERE organization_id IN (:org_a, :org_b)"),
                {"org_a": org_a, "org_b": org_b},
            )
            await connection.execute(
                text("DELETE FROM memberships WHERE organization_id IN (:org_a, :org_b)"),
                {"org_a": org_a, "org_b": org_b},
            )
            await connection.execute(
                text("DELETE FROM organizations WHERE id IN (:org_a, :org_b)"),
                {"org_a": org_a, "org_b": org_b},
            )
            await connection.execute(
                text("DELETE FROM users WHERE id IN (:user_a, :user_b)"),
                {"user_a": user_a, "user_b": user_b},
            )
        await engine.dispose()
