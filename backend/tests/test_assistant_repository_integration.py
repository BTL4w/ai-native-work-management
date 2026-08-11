"""PostgreSQL Assistant repository isolation, dedupe and queue tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.core.database import create_database_engine, create_session_factory
from app.modules.assistant.adapters.database_models import (
    AgentCheckpointModel,
    AgentHandoffModel,
    AgentRunModel,
    AssistantEventModel,
    AssistantJobModel,
    AssistantMessageModel,
    AssistantTurnModel,
    OrchestrationRunModel,
)
from app.modules.assistant.adapters.transaction import PostgreSQLAssistantTransactionFactory
from app.modules.assistant.domain.models import (
    AgentCheckpoint,
    AgentHandoffRecord,
    AgentRun,
    AssistantConversation,
    AssistantEvent,
    AssistantJob,
    AssistantMessage,
    AssistantTurn,
    MessageRole,
    OrchestrationRun,
)
from app.modules.audit.adapters.database_models import AuditEventModel
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.adapters.database_models import IdempotencyRecordModel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="requires PostgreSQL"),
]


def _actor(org: UUID, membership: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email=f"{membership.hex}@example.test",
        display_name="Assistant tester",
        membership_id=membership,
        organization_id=org,
        organization_name="Assistant test",
        role=MembershipRole.MANAGER,
    )


async def _seed_members(connection: object, pairs: tuple[tuple[UUID, UUID], ...]) -> None:
    for organization_id, membership_id in pairs:
        user_id = uuid4()
        await connection.execute(  # type: ignore[attr-defined]
            text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, 'Assistant')"),
            {"id": organization_id, "slug": f"assistant-{organization_id.hex}"},
        )
        await connection.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO users "
                "(id, email_normalized, email_display, display_name, password_hash) "
                "VALUES (:id, :email, :email, 'Assistant', 'hash')"
            ),
            {"id": user_id, "email": f"{user_id.hex}@example.test"},
        )
        await connection.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :org, :user, 'MANAGER')"
            ),
            {"id": membership_id, "org": organization_id, "user": user_id},
        )


def _turn_graph(
    *, conversation: AssistantConversation, actor: AuthenticatedActor
) -> tuple[AssistantMessage, AssistantTurn, OrchestrationRun, AssistantJob, AssistantEvent]:
    message_id, turn_id, run_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    message = AssistantMessage(
        id=message_id,
        organization_id=actor.organization_id,
        conversation_id=conversation.id,
        sequence=1,
        role=MessageRole.USER,
        content_blocks=({"kind": "text", "text": "Plan a customer event"},),
        created_by_membership_id=actor.membership_id,
        turn_id=turn_id,
        dedupe_key="message-1",
        created_at=now,
    )
    turn = AssistantTurn.create(
        id=turn_id,
        organization_id=actor.organization_id,
        conversation_id=conversation.id,
        user_message_id=message_id,
        actor_membership_id=actor.membership_id,
        objective="Plan a customer event",
        locale="en",
        now=now,
    )
    run = OrchestrationRun.create(
        id=run_id,
        organization_id=actor.organization_id,
        turn_id=turn_id,
        orchestrator_version="1.0.0",
        orchestrator_fingerprint="manifest-sha",
        execution_plan={"steps": []},
        budget={"max_iterations": 8},
        now=now,
    )
    job = AssistantJob.create(
        organization_id=actor.organization_id,
        conversation_id=conversation.id,
        turn_id=turn_id,
        orchestration_run_id=run_id,
        requester_membership_id=actor.membership_id,
        payload={"turn_id": str(turn_id)},
        now=now,
    )
    event = AssistantEvent(
        id=uuid4(),
        organization_id=actor.organization_id,
        conversation_id=conversation.id,
        sequence=1,
        event_type="assistant.turn.queued.v1",
        public_payload={"turn_id": str(turn_id), "status": "QUEUED"},
        turn_id=turn_id,
        orchestration_run_id=run_id,
        dedupe_key="turn-queued-1",
        occurred_at=now,
    )
    return message, turn, run, job, event


@pytest.mark.asyncio
async def test_owner_snapshot_isolated_and_conversation_creation_replays() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, owner_id, other_id, foreign_org, foreign_member = (uuid4() for _ in range(5))
    owner, other, foreign = (
        _actor(organization_id, owner_id),
        _actor(organization_id, other_id),
        _actor(foreign_org, foreign_member),
    )
    try:
        async with engine.begin() as connection:
            await _seed_members(
                connection,
                ((organization_id, owner_id), (foreign_org, foreign_member)),
            )
            other_user = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'Other', 'hash')"
                ),
                {"id": other_user, "email": f"{other_user.hex}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, 'MANAGER')"
                ),
                {"id": other_id, "org": organization_id, "user": other_user},
            )

        factory = PostgreSQLAssistantTransactionFactory(create_session_factory(engine))
        conversation = AssistantConversation.create(
            organization_id=organization_id,
            owner_membership_id=owner_id,
            locale="vi",
            title="Kế hoạch sự kiện",
        )
        async with factory(owner) as transaction:
            created = await transaction.repository.create_conversation_mutation(
                actor=owner,
                conversation=conversation,
                request_id="req-create-1",
                idempotency_key="conversation-key",
                request_fingerprint="fingerprint-a",
            )
            await transaction.commit()
        async with factory(owner) as transaction:
            replay = await transaction.repository.create_conversation_mutation(
                actor=owner,
                conversation=conversation,
                request_id="req-create-2",
                idempotency_key="conversation-key",
                request_fingerprint="fingerprint-a",
            )
            await transaction.commit()

        assert created.replayed is False
        assert replay.replayed is True
        assert replay.conversation.id == conversation.id
        async with factory(owner) as transaction:
            assert (
                await transaction.repository.get_conversation_snapshot(
                    actor=owner, conversation_id=conversation.id
                )
                is not None
            )
        async with factory(other) as transaction:
            assert (
                await transaction.repository.get_conversation_snapshot(
                    actor=other, conversation_id=conversation.id
                )
                is None
            )
        async with factory(foreign) as transaction:
            assert (
                await transaction.repository.get_conversation_snapshot(
                    actor=foreign, conversation_id=conversation.id
                )
                is None
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_message_turn_job_and_event_are_atomic_and_retry_safe() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, membership_id = uuid4(), uuid4()
    actor = _actor(organization_id, membership_id)
    try:
        async with engine.begin() as connection:
            await _seed_members(connection, ((organization_id, membership_id),))
        factory = PostgreSQLAssistantTransactionFactory(create_session_factory(engine))
        conversation = AssistantConversation.create(
            organization_id=organization_id, owner_membership_id=membership_id, locale="en"
        )
        async with factory(actor) as transaction:
            await transaction.repository.create_conversation_mutation(
                actor=actor,
                conversation=conversation,
                request_id="req-create",
                idempotency_key="create-key",
                request_fingerprint="create-fingerprint",
            )
            await transaction.commit()
        message, turn, run, job, event = _turn_graph(conversation=conversation, actor=actor)
        async with factory(actor) as transaction:
            first = await transaction.repository.submit_message_mutation(
                actor=actor,
                message=message,
                turn=turn,
                run=run,
                job=job,
                event=event,
                request_id="req-message-1",
                idempotency_key="message-key",
                request_fingerprint="message-fingerprint",
            )
            await transaction.commit()
        async with factory(actor) as transaction:
            replay = await transaction.repository.submit_message_mutation(
                actor=actor,
                message=message,
                turn=turn,
                run=run,
                job=job,
                event=event,
                request_id="req-message-2",
                idempotency_key="message-key",
                request_fingerprint="message-fingerprint",
            )
            await transaction.commit()

        assert first.replayed is False
        assert replay.replayed is True
        assert replay.turn.id == turn.id
        async with factory(actor) as transaction:
            session = transaction.session
            assert (
                await session.scalar(select(func.count()).select_from(AssistantMessageModel)) == 1
            )
            assert await session.scalar(select(func.count()).select_from(AssistantEventModel)) == 1
            assert await session.scalar(select(func.count()).select_from(AssistantJobModel)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_submit_failure_after_ordered_flush_rolls_back_the_entire_graph() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, membership_id = uuid4(), uuid4()
    actor = _actor(organization_id, membership_id)
    try:
        async with engine.begin() as connection:
            await _seed_members(connection, ((organization_id, membership_id),))
        factory = PostgreSQLAssistantTransactionFactory(create_session_factory(engine))
        conversation = AssistantConversation.create(
            organization_id=organization_id, owner_membership_id=membership_id, locale="en"
        )
        async with factory(actor) as transaction:
            await transaction.repository.create_conversation_mutation(
                actor=actor,
                conversation=conversation,
                request_id="req-create",
                idempotency_key="create-key",
                request_fingerprint="create-fingerprint",
            )
            await transaction.commit()

        message, turn, run, job, event = _turn_graph(conversation=conversation, actor=actor)
        invalid_event = AssistantEvent(
            id=event.id,
            organization_id=event.organization_id,
            conversation_id=event.conversation_id,
            sequence=event.sequence,
            event_type=event.event_type,
            public_payload=event.public_payload,
            turn_id=event.turn_id,
            orchestration_run_id=event.orchestration_run_id,
            agent_run_id=uuid4(),
            dedupe_key=event.dedupe_key,
            occurred_at=event.occurred_at,
        )
        with pytest.raises(DBAPIError):
            async with factory(actor) as transaction:
                await transaction.repository.submit_message_mutation(
                    actor=actor,
                    message=message,
                    turn=turn,
                    run=run,
                    job=job,
                    event=invalid_event,
                    request_id="req-message-fails",
                    idempotency_key="message-key-fails",
                    request_fingerprint="message-fingerprint-fails",
                )

        async with factory(actor) as transaction:
            session = transaction.session
            assert (
                await session.scalar(select(func.count()).select_from(AssistantMessageModel)) == 0
            )
            assert await session.scalar(select(func.count()).select_from(AssistantTurnModel)) == 0
            assert (
                await session.scalar(select(func.count()).select_from(OrchestrationRunModel)) == 0
            )
            assert await session.scalar(select(func.count()).select_from(AssistantJobModel)) == 0
            assert await session.scalar(select(func.count()).select_from(AssistantEventModel)) == 0
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(AuditEventModel.action == "assistant.message.submitted")
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecordModel)
                    .where(IdempotencyRecordModel.idempotency_key == "message-key-fails")
                )
                == 0
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_claim_is_tenant_scoped_and_retry_lease_safe() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, membership_id = uuid4(), uuid4()
    actor = _actor(organization_id, membership_id)
    try:
        async with engine.begin() as connection:
            await _seed_members(connection, ((organization_id, membership_id),))
        factory = PostgreSQLAssistantTransactionFactory(create_session_factory(engine))
        conversation = AssistantConversation.create(
            organization_id=organization_id, owner_membership_id=membership_id, locale="en"
        )
        async with factory(actor) as transaction:
            await transaction.repository.create_conversation_mutation(
                actor=actor,
                conversation=conversation,
                request_id="req-create",
                idempotency_key="create-key",
                request_fingerprint="create-fingerprint",
            )
            await transaction.commit()
        message, turn, run, job, event = _turn_graph(conversation=conversation, actor=actor)
        async with factory(actor) as transaction:
            await transaction.repository.submit_message_mutation(
                actor=actor,
                message=message,
                turn=turn,
                run=run,
                job=job,
                event=event,
                request_id="req-message",
                idempotency_key="message-key",
                request_fingerprint="message-fingerprint",
            )
            await transaction.commit()

        now = datetime.now(UTC)
        async with factory(organization_id) as transaction:
            claimed = await transaction.repository.claim_job(
                organization_id=organization_id,
                worker_id="assistant-worker-1",
                now=now,
                lease_until=now + timedelta(minutes=1),
            )
            await transaction.commit()
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.attempt_count == 1

        agent_run = AgentRun.create(
            organization_id=organization_id,
            orchestration_run_id=run.id,
            agent_id="work_management_orchestrator",
            agent_version="1.0.0",
            manifest_fingerprint="orchestrator-manifest-sha",
            capability="route_assistant_turn",
            typed_input={"turn_id": str(turn.id)},
            budget={"max_iterations": 8},
            now=now,
        )
        handoff = AgentHandoffRecord(
            id=uuid4(),
            organization_id=organization_id,
            orchestration_run_id=run.id,
            parent_agent_run_id=agent_run.id,
            target_agent_id="planning_specialist",
            target_agent_version="1.0.0",
            capability="create_plan_proposal",
            objective="Create a bounded project plan",
            typed_input={"objective": "Plan a customer event"},
            context_references=(),
            budget={"max_iterations": 4},
            step_id="plan-step-1",
            idempotency_key="handoff-key-1",
            dedupe_key="handoff-dedupe-1",
            created_at=now,
        )
        checkpoint = AgentCheckpoint(
            id=uuid4(),
            organization_id=organization_id,
            orchestration_run_id=run.id,
            agent_run_id=agent_run.id,
            sequence=1,
            node="route_intent",
            typed_state={"intent": "planning"},
            checkpoint_version="1.0.0",
            created_at=now,
        )
        progress_event = AssistantEvent(
            id=uuid4(),
            organization_id=organization_id,
            conversation_id=conversation.id,
            sequence=2,
            event_type="assistant.agent.started.v1",
            public_payload={"agent": "planning_specialist"},
            turn_id=turn.id,
            orchestration_run_id=run.id,
            agent_run_id=agent_run.id,
            dedupe_key="agent-started-1",
            occurred_at=now,
        )
        async with factory(organization_id) as transaction:
            started = await transaction.repository.begin_orchestration(job=claimed)
            await transaction.repository.append_agent_run(run=agent_run)
            await transaction.repository.append_handoff(handoff=handoff)
            await transaction.repository.save_checkpoint(checkpoint=checkpoint)
            await transaction.repository.append_event(event=progress_event)
            await transaction.repository.complete_job(
                job_id=claimed.id, worker_id="assistant-worker-1"
            )
            await transaction.commit()

        assert started.status.value == "RUNNING"
        async with factory(organization_id) as transaction:
            session = transaction.session
            assert await session.scalar(select(func.count()).select_from(AgentRunModel)) == 1
            assert await session.scalar(select(func.count()).select_from(AgentHandoffModel)) == 1
            assert await session.scalar(select(func.count()).select_from(AgentCheckpointModel)) == 1
            assert await session.scalar(select(func.count()).select_from(AssistantEventModel)) == 2
        async with factory(uuid4()) as transaction:
            assert (
                await transaction.repository.claim_job(
                    organization_id=uuid4(),
                    worker_id="assistant-worker-foreign",
                    now=now,
                    lease_until=now + timedelta(minutes=1),
                )
                is None
            )
    finally:
        await engine.dispose()
