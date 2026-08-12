"""Task 8 bounded worker ordering contract and PostgreSQL test marker."""

# pyright: reportArgumentType=false

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.core.config import Settings
from app.core.database import create_database_engine, create_session_factory
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.adapters.database_models import (
    ApprovalModel,
    ProposalVersionModel,
    WorkflowJobModel,
)
from app.modules.planning_runs.adapters.transaction import (
    PostgreSQLPlanningRunTransactionFactory,
)
from app.modules.planning_runs.domain.models import (
    Approval,
    Proposal,
    ProposalVersion,
    WorkflowRun,
)
from app.modules.work.adapters.database_models import ProjectModel, TaskModel
from app.worker import process_tenant_once


@pytest.mark.asyncio
async def test_worker_projection_step_remains_bounded_and_fair() -> None:
    calls: list[str] = []

    class Outbox:
        async def dispatch_once(self, *_):
            calls.append("outbox")
            return True

    class Assistant:
        async def run_once(self, **_):
            calls.append("assistant")
            return True

    class Planning:
        async def run_once(self, *_):
            calls.append("planning")
            return True

    class Projection:
        async def project_once(self, **_):
            calls.append("projection")
            return 1

    processed = await process_tenant_once(
        worker_id="worker",
        organization_id=uuid4(),
        outbox_service=Outbox(),
        assistant_job_service=Assistant(),
        planning_job_service=Planning(),
        projection_service=Projection(),
    )

    assert processed is True
    assert calls == ["outbox", "assistant", "planning", "projection"]


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL")
@pytest.mark.asyncio
async def test_concurrent_revisions_append_only_one_new_version() -> None:
    engine = create_database_engine(Settings(environment="test"))
    sessions = create_session_factory(engine)
    transactions = PostgreSQLPlanningRunTransactionFactory(sessions)
    organization_id, user_id, membership_id = uuid4(), uuid4(), uuid4()
    actor = AuthenticatedActor(
        user_id=user_id,
        email="revision@example.test",
        display_name="Revision Manager",
        membership_id=membership_id,
        organization_id=organization_id,
        organization_name="Revision tenant",
        role=MembershipRole.MANAGER,
    )
    run = WorkflowRun.create(
        organization_id=organization_id,
        project_id=None,
        requested_by_membership_id=membership_id,
        workflow_name="project_planning",
        workflow_version="1.0.0",
        verifier_version="1.0.0",
        input_goal_text="Plan a launch",
    )
    approval = Approval.create(
        organization_id=organization_id,
        proposal_id=uuid4(),
        proposal_version_number=1,
    )
    proposal = Proposal.create(
        id=approval.proposal_id,
        organization_id=organization_id,
        workflow_run_id=run.id,
    )
    approval = Approval.create(
        id=approval.id,
        organization_id=organization_id,
        proposal_id=proposal.id,
        proposal_version_number=1,
    )
    base_content: dict[str, object] = {
        "project": {
            "title": "Launch",
            "description": None,
            "start_date": None,
            "due_date": None,
        },
        "goal": {
            "title": "Launch goal",
            "description": None,
            "expected_outcomes": ["Reviewed outcome"],
            "target_date": None,
        },
        "milestones": [],
        "tasks": [],
        "dependencies": [],
        "assumptions": [],
    }
    version = ProposalVersion(
        id=uuid4(),
        organization_id=organization_id,
        proposal_id=proposal.id,
        version_number=1,
        created_by_membership_id=membership_id,
        content=base_content,
        assumptions=[],
        source_reference_snapshot=[],
        workflow_version="1.0.0",
        prompt_version="planning.v1",
        schema_version="planning-proposal.v1",
        model_reference="mock:base",
        verifier_version="1.0.0",
        creator_type="AI_SYSTEM",
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, 'Revision')"),
                {"id": organization_id, "slug": f"revision-{organization_id.hex}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'Revision', 'hash')"
                ),
                {"id": user_id, "email": f"{user_id.hex}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, 'MANAGER')"
                ),
                {"id": membership_id, "org": organization_id, "user": user_id},
            )
        async with transactions(actor) as transaction:
            await transaction.repository.create_workflow_run(run=run)
            await transaction.repository.create_proposal(
                proposal=proposal,
                initial_version=version,
            )
            await transaction.repository.create_approval(approval=approval)
            await transaction.repository.update_proposal(
                actor=actor,
                proposal=proposal.mark_ready_for_decision(approval.id),
            )
            await transaction.commit()

        async def finalize(label: str):
            async with transactions(actor) as transaction:
                result = await transaction.repository.finalize_ai_revision_mutation(
                    actor=actor,
                    proposal_id=proposal.id,
                    base_version=1,
                    content=base_content,
                    change_summary=label,
                    model_reference=f"mock:{label}",
                    validation_result={"can_approve": True, "errors": [], "warnings": []},
                    request_id=f"request-{label}",
                    idempotency_key=f"revision-{label}",
                )
                await transaction.commit()
                return result

        results = await asyncio.gather(finalize("a"), finalize("b"))
        assert sum(result is not None for result in results) == 1

        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ProposalVersionModel)
                    .where(
                        ProposalVersionModel.organization_id == organization_id,
                        ProposalVersionModel.proposal_id == proposal.id,
                    )
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkflowJobModel)
                    .where(
                        WorkflowJobModel.organization_id == organization_id,
                        WorkflowJobModel.workflow_run_id == run.id,
                        WorkflowJobModel.job_type == "proposal.revalidate",
                    )
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(ApprovalModel.status).where(
                        ApprovalModel.organization_id == organization_id,
                        ApprovalModel.id == approval.id,
                    )
                )
                == "SUPERSEDED"
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ProjectModel)
                    .where(ProjectModel.organization_id == organization_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(TaskModel)
                    .where(TaskModel.organization_id == organization_id)
                )
                == 0
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM workflow_runs WHERE organization_id = :id"),
                {"id": organization_id},
            )
            await connection.execute(
                text("DELETE FROM audit_events WHERE organization_id = :id"),
                {"id": organization_id},
            )
            await connection.execute(
                text("DELETE FROM idempotency_records WHERE organization_id = :id"),
                {"id": organization_id},
            )
            await connection.execute(
                text("DELETE FROM memberships WHERE organization_id = :id"),
                {"id": organization_id},
            )
            await connection.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": user_id},
            )
            await connection.execute(
                text("DELETE FROM organizations WHERE id = :id"),
                {"id": organization_id},
            )
        await engine.dispose()
