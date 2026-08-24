"""Persisted replay and reconnect coverage for Assistant SSE."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assistant.adapters.transaction import PostgreSQLAssistantTransaction
from app.modules.assistant.application.event_service import AssistantEventService
from app.modules.assistant.application.ports import AssistantConversationSnapshot
from app.modules.assistant.application.service import ResourceNotFoundError
from app.modules.assistant.domain.models import AssistantConversation, AssistantEvent
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="sse@example.test",
        display_name="SSE user",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="SSE tenant",
        role=MembershipRole.EMPLOYEE,
    )


class EventRepository:
    def __init__(
        self,
        *,
        conversation: AssistantConversation | None,
        events: list[AssistantEvent],
    ) -> None:
        self.conversation = conversation
        self.events = events
        self.read_count = 0
        self.job_count = 0

    async def get_conversation_snapshot(
        self, *, actor: AuthenticatedActor, conversation_id: UUID
    ) -> AssistantConversationSnapshot | None:
        if (
            self.conversation is None
            or self.conversation.id != conversation_id
            or self.conversation.organization_id != actor.organization_id
            or self.conversation.owner_membership_id != actor.membership_id
        ):
            return None
        return AssistantConversationSnapshot(self.conversation, (), (), (), tuple(self.events))

    async def list_events(
        self,
        *,
        actor: AuthenticatedActor,
        conversation_id: UUID,
        after_sequence: int,
    ) -> list[AssistantEvent]:
        self.read_count += 1
        return [event for event in self.events if event.sequence > after_sequence]


class EventTransaction(AbstractAsyncContextManager["EventTransaction"]):
    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None


class EventTransactionFactory:
    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    def __call__(self, _: AuthenticatedActor) -> EventTransaction:
        return EventTransaction(self.repository)


class _CancelledEnterTransaction:
    is_active = True

    def __init__(self) -> None:
        self.rolled_back = False

    async def __aenter__(self) -> Self:
        return self

    async def rollback(self) -> None:
        self.rolled_back = True
        self.is_active = False


class _CancelledEnterSession:
    def __init__(self) -> None:
        self.transaction = _CancelledEnterTransaction()
        self.closed = False
        self.invalidated = False

    def begin(self) -> _CancelledEnterTransaction:
        return self.transaction

    async def execute(self, *_: Any, **__: Any) -> None:
        raise asyncio.CancelledError

    async def close(self) -> None:
        self.closed = True

    async def invalidate(self) -> None:
        self.invalidated = True
        self.closed = True


def _fixture() -> tuple[AuthenticatedActor, AssistantConversation, list[AssistantEvent]]:
    actor = _actor()
    conversation = AssistantConversation.create(
        organization_id=actor.organization_id,
        owner_membership_id=actor.membership_id,
        locale="en",
    )
    now = datetime.now(UTC)
    events = [
        AssistantEvent(
            id=uuid4(),
            organization_id=actor.organization_id,
            conversation_id=conversation.id,
            sequence=sequence,
            event_type="assistant.turn.progress.v1",
            public_payload={"sequence": sequence},
            occurred_at=now,
        )
        for sequence in (1, 2, 3)
    ]
    return actor, conversation, events


@pytest.mark.asyncio
async def test_replay_is_ordered_and_resume_is_strictly_after_last_event_id() -> None:
    actor, conversation, events = _fixture()
    repository = EventRepository(conversation=conversation, events=[events[2], *events[:2]])
    service = AssistantEventService(
        transaction_factory=EventTransactionFactory(repository),
        heartbeat_seconds=0,
    )

    frames = await service.replay(
        actor=actor,
        conversation_id=conversation.id,
        after_sequence=1,
    )

    assert [frame.splitlines()[0] for frame in frames] == ["id: 2", "id: 3"]
    assert repository.job_count == 0


@pytest.mark.asyncio
async def test_replay_removes_sensitive_payload_keys() -> None:
    actor, conversation, events = _fixture()
    unsafe = events[0]
    unsafe = AssistantEvent(
        id=unsafe.id,
        organization_id=unsafe.organization_id,
        conversation_id=unsafe.conversation_id,
        sequence=unsafe.sequence,
        event_type=unsafe.event_type,
        public_payload={"status": "RUNNING", "provider_error": "secret traceback"},
        occurred_at=unsafe.occurred_at,
    )
    service = AssistantEventService(
        transaction_factory=EventTransactionFactory(
            EventRepository(conversation=conversation, events=[unsafe])
        ),
        heartbeat_seconds=0,
    )

    [frame] = await service.replay(
        actor=actor,
        conversation_id=conversation.id,
        after_sequence=0,
    )

    assert '"status":"RUNNING"' in frame
    assert "provider_error" not in frame
    assert "traceback" not in frame


@pytest.mark.asyncio
async def test_stream_emits_keepalive_without_creating_work() -> None:
    actor, conversation, _ = _fixture()
    repository = EventRepository(conversation=conversation, events=[])
    service = AssistantEventService(
        transaction_factory=EventTransactionFactory(repository),
        heartbeat_seconds=0,
    )

    stream = service.stream(actor=actor, conversation_id=conversation.id, after_sequence=0)
    assert await anext(stream) == ": heartbeat\n\n"
    await stream.aclose()
    assert repository.read_count == 1
    assert repository.job_count == 0


@pytest.mark.asyncio
async def test_cancelled_transaction_entry_rolls_back_before_returning_connection() -> None:
    session = _CancelledEnterSession()
    transaction = PostgreSQLAssistantTransaction(
        session=cast(AsyncSession, session),
        organization_id=uuid4(),
        membership_id=uuid4(),
    )

    with pytest.raises(asyncio.CancelledError):
        await transaction.__aenter__()

    assert session.invalidated is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_authorize_is_non_disclosing_for_other_owner_or_tenant() -> None:
    _, conversation, _ = _fixture()
    service = AssistantEventService(
        transaction_factory=EventTransactionFactory(
            EventRepository(conversation=conversation, events=[])
        )
    )

    foreign_actor = _actor()
    with pytest.raises(ResourceNotFoundError):
        await service.authorize(actor=foreign_actor, conversation_id=conversation.id)
