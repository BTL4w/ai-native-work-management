"""PostgreSQL repository for durable Assistant transcript and Agent execution state."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assistant.adapters.database_models import (
    AgentCheckpointModel,
    AgentHandoffModel,
    AgentRunModel,
    AssistantConversationModel,
    AssistantEventModel,
    AssistantJobModel,
    AssistantMessageModel,
    AssistantTurnModel,
    OrchestrationRunModel,
)
from app.modules.assistant.application.ports import (
    AssistantConversationMutationResult,
    AssistantConversationSnapshot,
    AssistantTurnMutationResult,
)
from app.modules.assistant.domain.models import (
    AgentCheckpoint,
    AgentHandoffRecord,
    AgentRun,
    AssistantConversation,
    AssistantEvent,
    AssistantIdempotencyKeyReusedError,
    AssistantJob,
    AssistantJobStatus,
    AssistantMessage,
    AssistantTurn,
    AssistantTurnStatus,
    ConversationStatus,
    MessageRole,
    OrchestrationRun,
    OrchestrationRunStatus,
)
from app.modules.audit.adapters.database_models import AuditEventModel
from app.modules.audit.domain.events import AuditOutcome
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.work.adapters.database_models import IdempotencyRecordModel, IdempotencyState

_IDEMPOTENCY_TTL = timedelta(hours=24)


def _conversation(model: AssistantConversationModel) -> AssistantConversation:
    return AssistantConversation(
        id=model.id,
        organization_id=model.organization_id,
        owner_membership_id=model.owner_membership_id,
        locale=model.locale,  # type: ignore[arg-type]
        title=model.title,
        status=ConversationStatus(model.status),
        version=model.version,
        last_message_sequence=model.last_message_sequence,
        last_event_sequence=model.last_event_sequence,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _message(model: AssistantMessageModel) -> AssistantMessage:
    return AssistantMessage(
        id=model.id,
        organization_id=model.organization_id,
        conversation_id=model.conversation_id,
        sequence=model.sequence,
        role=MessageRole(model.role),
        content_blocks=tuple(model.content_blocks),
        created_by_membership_id=model.created_by_membership_id,
        turn_id=model.turn_id,
        dedupe_key=model.dedupe_key,
        created_at=model.created_at,
    )


def _turn(model: AssistantTurnModel) -> AssistantTurn:
    return AssistantTurn(
        id=model.id,
        organization_id=model.organization_id,
        conversation_id=model.conversation_id,
        user_message_id=model.user_message_id,
        actor_membership_id=model.actor_membership_id,
        objective=model.objective,
        locale=model.locale,  # type: ignore[arg-type]
        status=AssistantTurnStatus(model.status),
        safe_error_code=model.safe_error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _run(model: OrchestrationRunModel) -> OrchestrationRun:
    return OrchestrationRun(
        id=model.id,
        organization_id=model.organization_id,
        turn_id=model.turn_id,
        orchestrator_version=model.orchestrator_version,
        orchestrator_fingerprint=model.orchestrator_fingerprint,
        execution_plan=model.execution_plan,
        checkpoint=model.checkpoint,
        budget=model.budget,
        usage=model.usage,
        status=OrchestrationRunStatus(model.status),
        stop_reason=model.stop_reason,
        safe_error_code=model.safe_error_code,
        created_at=model.created_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        updated_at=model.updated_at,
    )


def _job(model: AssistantJobModel) -> AssistantJob:
    return AssistantJob(
        id=model.id,
        organization_id=model.organization_id,
        conversation_id=model.conversation_id,
        turn_id=model.turn_id,
        orchestration_run_id=model.orchestration_run_id,
        requester_membership_id=model.requester_membership_id,
        job_type="assistant.turn.execute",
        payload=model.payload,
        status=AssistantJobStatus(model.status),
        attempt_count=model.attempt_count,
        max_attempts=model.max_attempts,
        available_at=model.available_at,
        locked_by=model.locked_by,
        lease_until=model.lease_until,
        safe_error_code=model.safe_error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _event(model: AssistantEventModel) -> AssistantEvent:
    return AssistantEvent(
        id=model.id,
        organization_id=model.organization_id,
        conversation_id=model.conversation_id,
        sequence=model.sequence,
        event_type=model.event_type,
        public_payload=model.public_payload,
        turn_id=model.turn_id,
        orchestration_run_id=model.orchestration_run_id,
        agent_run_id=model.agent_run_id,
        source_type=model.source_type,
        source_id=model.source_id,
        source_sequence=model.source_sequence,
        dedupe_key=model.dedupe_key,
        occurred_at=model.occurred_at,
    )


class PostgreSQLAssistantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _idempotency(
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        key: str,
        fingerprint: str,
    ) -> IdempotencyRecordModel | None:
        record = await self._session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.organization_id == actor.organization_id,
                IdempotencyRecordModel.actor_membership_id == actor.membership_id,
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.idempotency_key == key,
            )
        )
        if record is None:
            return None
        if (
            record.request_fingerprint != fingerprint
            or record.state is not IdempotencyState.COMPLETED
            or record.response_body is None
        ):
            raise AssistantIdempotencyKeyReusedError("IDEMPOTENCY_KEY_REUSED")
        return record

    def _new_idempotency(
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        key: str,
        fingerprint: str,
        now: datetime,
    ) -> IdempotencyRecordModel:
        model = IdempotencyRecordModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            actor_membership_id=actor.membership_id,
            operation=operation,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            state=IdempotencyState.IN_PROGRESS,
            response_status=None,
            response_body=None,
            created_at=now,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        self._session.add(model)
        return model

    def _audit(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        resource_type: str,
        resource_id: UUID,
        request_id: str,
        idempotency_key: str,
    ) -> None:
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=AuditOutcome.SUCCEEDED,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data={},
                after_data={"status": "COMMITTED"},
                reason_data={},
            )
        )

    async def create_conversation_mutation(
        self,
        *,
        actor: AuthenticatedActor,
        conversation: AssistantConversation,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> AssistantConversationMutationResult:
        operation = "assistant.conversation.create"
        replay = await self._idempotency(
            actor=actor,
            operation=operation,
            key=idempotency_key,
            fingerprint=request_fingerprint,
        )
        if replay is not None:
            response_body = replay.response_body
            if response_body is None:
                raise AssistantDomainLookupError("ASSISTANT_REPLAY_NOT_FOUND")
            conversation_id = UUID(str(response_body["conversation_id"]))
            model = await self._session.scalar(
                select(AssistantConversationModel).where(
                    AssistantConversationModel.organization_id == actor.organization_id,
                    AssistantConversationModel.owner_membership_id == actor.membership_id,
                    AssistantConversationModel.id == conversation_id,
                )
            )
            if model is None:
                raise AssistantDomainLookupError("ASSISTANT_REPLAY_NOT_FOUND")
            return AssistantConversationMutationResult(
                conversation=_conversation(model), replayed=True
            )
        if (
            conversation.organization_id != actor.organization_id
            or conversation.owner_membership_id != actor.membership_id
        ):
            raise AssistantDomainLookupError("ASSISTANT_CONVERSATION_NOT_FOUND")
        now = datetime.now(UTC)
        record = self._new_idempotency(
            actor=actor,
            operation=operation,
            key=idempotency_key,
            fingerprint=request_fingerprint,
            now=now,
        )
        self._session.add(
            AssistantConversationModel(
                id=conversation.id,
                organization_id=conversation.organization_id,
                owner_membership_id=conversation.owner_membership_id,
                locale=conversation.locale,
                title=conversation.title,
                status=conversation.status.value,
                version=conversation.version,
                last_message_sequence=conversation.last_message_sequence,
                last_event_sequence=conversation.last_event_sequence,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
        self._audit(
            actor=actor,
            action="assistant.conversation.created",
            resource_type="assistant_conversation",
            resource_id=conversation.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201
        record.response_body = {"conversation_id": str(conversation.id)}
        await self._session.flush()
        return AssistantConversationMutationResult(conversation=conversation, replayed=False)

    async def submit_message_mutation(
        self,
        *,
        actor: AuthenticatedActor,
        message: AssistantMessage,
        turn: AssistantTurn,
        run: OrchestrationRun,
        job: AssistantJob,
        event: AssistantEvent,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> AssistantTurnMutationResult:
        operation = f"assistant.message.submit:{message.conversation_id}"
        replay = await self._idempotency(
            actor=actor,
            operation=operation,
            key=idempotency_key,
            fingerprint=request_fingerprint,
        )
        if replay is not None:
            response_body = replay.response_body
            if response_body is None:
                raise AssistantDomainLookupError("ASSISTANT_REPLAY_NOT_FOUND")
            return await self._load_turn_result(
                actor=actor,
                message_id=UUID(str(response_body["message_id"])),
                turn_id=UUID(str(response_body["turn_id"])),
                replayed=True,
            )
        identifiers = {
            message.organization_id,
            turn.organization_id,
            run.organization_id,
            job.organization_id,
            event.organization_id,
        }
        if (
            identifiers != {actor.organization_id}
            or turn.actor_membership_id != actor.membership_id
        ):
            raise AssistantDomainLookupError("ASSISTANT_CONVERSATION_NOT_FOUND")
        conversation_model = await self._session.scalar(
            select(AssistantConversationModel)
            .where(
                AssistantConversationModel.organization_id == actor.organization_id,
                AssistantConversationModel.owner_membership_id == actor.membership_id,
                AssistantConversationModel.id == message.conversation_id,
                AssistantConversationModel.status == ConversationStatus.ACTIVE.value,
            )
            .with_for_update()
        )
        if conversation_model is None:
            raise AssistantDomainLookupError("ASSISTANT_CONVERSATION_NOT_FOUND")
        message = replace(
            message,
            sequence=conversation_model.last_message_sequence + 1,
        )
        event = replace(
            event,
            sequence=conversation_model.last_event_sequence + 1,
        )
        if (
            message.turn_id != turn.id
            or turn.user_message_id != message.id
            or run.turn_id != turn.id
            or job.orchestration_run_id != run.id
            or event.turn_id != turn.id
            or event.orchestration_run_id != run.id
        ):
            raise AssistantDomainLookupError("ASSISTANT_GRAPH_IDENTITY_INVALID")
        now = datetime.now(UTC)
        record = self._new_idempotency(
            actor=actor,
            operation=operation,
            key=idempotency_key,
            fingerprint=request_fingerprint,
            now=now,
        )
        message_model = AssistantMessageModel(
            id=message.id,
            organization_id=message.organization_id,
            conversation_id=message.conversation_id,
            sequence=message.sequence,
            role=message.role.value,
            content_blocks=list(message.content_blocks),
            created_by_membership_id=message.created_by_membership_id,
            turn_id=message.turn_id,
            dedupe_key=message.dedupe_key,
            created_at=message.created_at,
        )
        self._session.add(message_model)
        await self._session.flush()

        turn_model = AssistantTurnModel(
            id=turn.id,
            organization_id=turn.organization_id,
            conversation_id=turn.conversation_id,
            user_message_id=turn.user_message_id,
            actor_membership_id=turn.actor_membership_id,
            objective=turn.objective,
            locale=turn.locale,
            status=turn.status.value,
            safe_error_code=turn.safe_error_code,
            created_at=turn.created_at,
            updated_at=turn.updated_at,
        )
        self._session.add(turn_model)
        await self._session.flush()

        run_model = OrchestrationRunModel(
            id=run.id,
            organization_id=run.organization_id,
            turn_id=run.turn_id,
            orchestrator_version=run.orchestrator_version,
            orchestrator_fingerprint=run.orchestrator_fingerprint,
            execution_plan=run.execution_plan,
            checkpoint=run.checkpoint,
            budget=run.budget,
            usage=run.usage,
            status=run.status.value,
            stop_reason=run.stop_reason,
            safe_error_code=run.safe_error_code,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            updated_at=run.updated_at,
        )
        self._session.add(run_model)
        await self._session.flush()

        self._session.add_all(
            [
                AssistantJobModel(
                    id=job.id,
                    organization_id=job.organization_id,
                    conversation_id=job.conversation_id,
                    turn_id=job.turn_id,
                    orchestration_run_id=job.orchestration_run_id,
                    requester_membership_id=job.requester_membership_id,
                    job_type=job.job_type,
                    payload=job.payload,
                    status=job.status.value,
                    attempt_count=job.attempt_count,
                    max_attempts=job.max_attempts,
                    available_at=job.available_at,
                    locked_by=job.locked_by,
                    lease_until=job.lease_until,
                    safe_error_code=job.safe_error_code,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                ),
                AssistantEventModel(
                    id=event.id,
                    organization_id=event.organization_id,
                    conversation_id=event.conversation_id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    public_payload=event.public_payload,
                    turn_id=event.turn_id,
                    orchestration_run_id=event.orchestration_run_id,
                    agent_run_id=event.agent_run_id,
                    source_type=event.source_type,
                    source_id=event.source_id,
                    source_sequence=event.source_sequence,
                    dedupe_key=event.dedupe_key,
                    occurred_at=event.occurred_at,
                ),
            ]
        )
        conversation_model.last_message_sequence = message.sequence
        conversation_model.last_event_sequence = event.sequence
        conversation_model.version += 2
        conversation_model.updated_at = now
        self._audit(
            actor=actor,
            action="assistant.message.submitted",
            resource_type="assistant_turn",
            resource_id=turn.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 202
        record.response_body = {"message_id": str(message.id), "turn_id": str(turn.id)}
        await self._session.flush()
        return AssistantTurnMutationResult(
            message=message, turn=turn, run=run, job=job, event=event, replayed=False
        )

    async def _load_turn_result(
        self,
        *,
        actor: AuthenticatedActor,
        message_id: UUID,
        turn_id: UUID,
        replayed: bool,
    ) -> AssistantTurnMutationResult:
        message_model = await self._session.scalar(
            select(AssistantMessageModel).where(
                AssistantMessageModel.organization_id == actor.organization_id,
                AssistantMessageModel.id == message_id,
            )
        )
        turn_model = await self._session.scalar(
            select(AssistantTurnModel).where(
                AssistantTurnModel.organization_id == actor.organization_id,
                AssistantTurnModel.id == turn_id,
            )
        )
        run_model = await self._session.scalar(
            select(OrchestrationRunModel).where(
                OrchestrationRunModel.organization_id == actor.organization_id,
                OrchestrationRunModel.turn_id == turn_id,
            )
        )
        if message_model is None or turn_model is None or run_model is None:
            raise AssistantDomainLookupError("ASSISTANT_REPLAY_NOT_FOUND")
        job_model = await self._session.scalar(
            select(AssistantJobModel).where(
                AssistantJobModel.organization_id == actor.organization_id,
                AssistantJobModel.orchestration_run_id == run_model.id,
            )
        )
        event_model = await self._session.scalar(
            select(AssistantEventModel).where(
                AssistantEventModel.organization_id == actor.organization_id,
                AssistantEventModel.turn_id == turn_id,
            )
        )
        if job_model is None or event_model is None:
            raise AssistantDomainLookupError("ASSISTANT_REPLAY_NOT_FOUND")
        return AssistantTurnMutationResult(
            message=_message(message_model),
            turn=_turn(turn_model),
            run=_run(run_model),
            job=_job(job_model),
            event=_event(event_model),
            replayed=replayed,
        )

    async def get_conversation_snapshot(
        self, *, actor: AuthenticatedActor, conversation_id: UUID
    ) -> AssistantConversationSnapshot | None:
        conversation_model = await self._session.scalar(
            select(AssistantConversationModel).where(
                AssistantConversationModel.organization_id == actor.organization_id,
                AssistantConversationModel.owner_membership_id == actor.membership_id,
                AssistantConversationModel.id == conversation_id,
            )
        )
        if conversation_model is None:
            return None
        message_models = await self._session.scalars(
            select(AssistantMessageModel)
            .where(
                AssistantMessageModel.organization_id == actor.organization_id,
                AssistantMessageModel.conversation_id == conversation_id,
            )
            .order_by(AssistantMessageModel.sequence)
        )
        turn_models = await self._session.scalars(
            select(AssistantTurnModel)
            .where(
                AssistantTurnModel.organization_id == actor.organization_id,
                AssistantTurnModel.conversation_id == conversation_id,
            )
            .order_by(AssistantTurnModel.created_at, AssistantTurnModel.id)
        )
        turns = tuple(_turn(model) for model in turn_models)
        turn_ids = [turn.id for turn in turns]
        run_models = (
            await self._session.scalars(
                select(OrchestrationRunModel)
                .where(
                    OrchestrationRunModel.organization_id == actor.organization_id,
                    OrchestrationRunModel.turn_id.in_(turn_ids),
                )
                .order_by(OrchestrationRunModel.created_at, OrchestrationRunModel.id)
            )
            if turn_ids
            else ()
        )
        event_models = await self._session.scalars(
            select(AssistantEventModel)
            .where(
                AssistantEventModel.organization_id == actor.organization_id,
                AssistantEventModel.conversation_id == conversation_id,
            )
            .order_by(AssistantEventModel.sequence)
        )
        return AssistantConversationSnapshot(
            conversation=_conversation(conversation_model),
            messages=tuple(_message(model) for model in message_models),
            turns=turns,
            orchestration_runs=tuple(_run(model) for model in run_models),
            events=tuple(_event(model) for model in event_models),
        )

    async def list_conversations(
        self, *, actor: AuthenticatedActor, limit: int
    ) -> list[AssistantConversation]:
        models = await self._session.scalars(
            select(AssistantConversationModel)
            .where(
                AssistantConversationModel.organization_id == actor.organization_id,
                AssistantConversationModel.owner_membership_id == actor.membership_id,
            )
            .order_by(
                AssistantConversationModel.updated_at.desc(),
                AssistantConversationModel.id.desc(),
            )
            .limit(limit)
        )
        return [_conversation(m) for m in models]

    async def list_events(
        self,
        *,
        actor: AuthenticatedActor,
        conversation_id: UUID,
        after_sequence: int,
    ) -> list[AssistantEvent]:
        # Verify owner before listing
        conv = await self._session.scalar(
            select(AssistantConversationModel).where(
                AssistantConversationModel.organization_id == actor.organization_id,
                AssistantConversationModel.owner_membership_id == actor.membership_id,
                AssistantConversationModel.id == conversation_id,
            )
        )
        if conv is None:
            return []
        models = await self._session.scalars(
            select(AssistantEventModel)
            .where(
                AssistantEventModel.organization_id == actor.organization_id,
                AssistantEventModel.conversation_id == conversation_id,
                AssistantEventModel.sequence > after_sequence,
            )
            .order_by(AssistantEventModel.sequence)
        )
        return [_event(m) for m in models]

    async def append_rejected_audit(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        request_id: str,
        reason_code: str,
    ) -> None:
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=AuditOutcome.REJECTED,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                idempotency_key=None,
                before_data={},
                after_data={},
                reason_data={"code": reason_code},
            )
        )
        await self._session.flush()

    async def claim_job(
        self,
        *,
        organization_id: UUID,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> AssistantJob | None:
        model = await self._session.scalar(
            select(AssistantJobModel)
            .where(
                AssistantJobModel.organization_id == organization_id,
                AssistantJobModel.attempt_count < AssistantJobModel.max_attempts,
                AssistantJobModel.available_at <= now,
                (AssistantJobModel.status == AssistantJobStatus.QUEUED.value)
                | (
                    (AssistantJobModel.status == AssistantJobStatus.RUNNING.value)
                    & (AssistantJobModel.lease_until < now)
                ),
            )
            .order_by(AssistantJobModel.created_at, AssistantJobModel.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if model is None:
            return None
        model.status = AssistantJobStatus.RUNNING.value
        model.attempt_count += 1
        model.locked_by = worker_id
        model.lease_until = lease_until
        model.updated_at = now
        await self._session.flush()
        return _job(model)

    async def begin_orchestration(self, *, job: AssistantJob) -> OrchestrationRun:
        model = await self._session.scalar(
            select(OrchestrationRunModel)
            .where(
                OrchestrationRunModel.organization_id == job.organization_id,
                OrchestrationRunModel.id == job.orchestration_run_id,
            )
            .with_for_update()
        )
        if model is None:
            raise AssistantDomainLookupError("ORCHESTRATION_RUN_NOT_FOUND")
        run = _run(model).mark_running()
        model.status = run.status.value
        model.started_at = run.started_at
        model.updated_at = run.updated_at
        await self._session.flush()
        return run

    async def append_agent_run(self, *, run: AgentRun) -> AgentRun:
        self._session.add(
            AgentRunModel(
                id=run.id,
                organization_id=run.organization_id,
                orchestration_run_id=run.orchestration_run_id,
                parent_agent_run_id=run.parent_agent_run_id,
                inbound_handoff_id=run.inbound_handoff_id,
                agent_id=run.agent_id,
                agent_version=run.agent_version,
                manifest_fingerprint=run.manifest_fingerprint,
                capability=run.capability,
                typed_input=run.typed_input,
                typed_output=run.typed_output,
                version_metadata=run.version_metadata,
                budget=run.budget,
                usage=run.usage,
                status=run.status.value,
                stop_reason=run.stop_reason,
                safe_error_code=run.safe_error_code,
                workflow_run_id=run.workflow_run_id,
                projected_workflow_sequence=run.projected_workflow_sequence,
                created_at=run.created_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
                updated_at=run.updated_at,
            )
        )
        await self._session.flush()
        return run

    async def append_handoff(self, *, handoff: AgentHandoffRecord) -> None:
        self._session.add(
            AgentHandoffModel(
                id=handoff.id,
                organization_id=handoff.organization_id,
                orchestration_run_id=handoff.orchestration_run_id,
                parent_agent_run_id=handoff.parent_agent_run_id,
                target_agent_id=handoff.target_agent_id,
                target_agent_version=handoff.target_agent_version,
                capability=handoff.capability,
                objective=handoff.objective,
                typed_input=handoff.typed_input,
                context_references=list(handoff.context_references),
                budget=handoff.budget,
                step_id=handoff.step_id,
                idempotency_key=handoff.idempotency_key,
                dedupe_key=handoff.dedupe_key,
                created_at=handoff.created_at,
            )
        )
        await self._session.flush()

    async def save_checkpoint(self, *, checkpoint: AgentCheckpoint) -> None:
        self._session.add(
            AgentCheckpointModel(
                id=checkpoint.id,
                organization_id=checkpoint.organization_id,
                orchestration_run_id=checkpoint.orchestration_run_id,
                agent_run_id=checkpoint.agent_run_id,
                sequence=checkpoint.sequence,
                node=checkpoint.node,
                typed_state=checkpoint.typed_state,
                checkpoint_version=checkpoint.checkpoint_version,
                created_at=checkpoint.created_at,
            )
        )
        await self._session.flush()

    async def append_event(self, *, event: AssistantEvent) -> AssistantEvent:
        conversation = await self._session.scalar(
            select(AssistantConversationModel)
            .where(
                AssistantConversationModel.organization_id == event.organization_id,
                AssistantConversationModel.id == event.conversation_id,
            )
            .with_for_update()
        )
        if conversation is None or event.sequence != conversation.last_event_sequence + 1:
            raise AssistantDomainLookupError("ASSISTANT_EVENT_SEQUENCE_INVALID")
        self._session.add(
            AssistantEventModel(
                id=event.id,
                organization_id=event.organization_id,
                conversation_id=event.conversation_id,
                sequence=event.sequence,
                event_type=event.event_type,
                public_payload=event.public_payload,
                turn_id=event.turn_id,
                orchestration_run_id=event.orchestration_run_id,
                agent_run_id=event.agent_run_id,
                source_type=event.source_type,
                source_id=event.source_id,
                source_sequence=event.source_sequence,
                dedupe_key=event.dedupe_key,
                occurred_at=event.occurred_at,
            )
        )
        conversation.last_event_sequence = event.sequence
        conversation.version += 1
        conversation.updated_at = event.occurred_at
        await self._session.flush()
        return event

    async def complete_job(self, *, job_id: UUID, worker_id: str) -> None:
        await self._session.execute(
            update(AssistantJobModel)
            .where(
                AssistantJobModel.id == job_id,
                AssistantJobModel.status == AssistantJobStatus.RUNNING.value,
                AssistantJobModel.locked_by == worker_id,
            )
            .values(
                status=AssistantJobStatus.COMPLETED.value,
                locked_by=None,
                lease_until=None,
                updated_at=datetime.now(UTC),
            )
        )

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        next_available_at: datetime,
    ) -> None:
        model = await self._session.scalar(
            select(AssistantJobModel)
            .where(
                AssistantJobModel.id == job_id,
                AssistantJobModel.status == AssistantJobStatus.RUNNING.value,
                AssistantJobModel.locked_by == worker_id,
            )
            .with_for_update()
        )
        if model is None:
            raise AssistantDomainLookupError("ASSISTANT_JOB_LEASE_INVALID")
        model.status = (
            AssistantJobStatus.QUEUED.value
            if model.attempt_count < model.max_attempts
            else AssistantJobStatus.FAILED.value
        )
        model.safe_error_code = error_code
        model.available_at = next_available_at
        model.locked_by = None
        model.lease_until = None
        model.updated_at = datetime.now(UTC)
        await self._session.flush()


class AssistantDomainLookupError(ValueError):
    """Safe non-disclosing repository lookup failure."""
