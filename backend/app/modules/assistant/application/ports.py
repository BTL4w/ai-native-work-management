"""Typed repository and transaction boundaries for durable Assistant execution."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.assistant.domain.models import (
    AgentCheckpoint,
    AgentHandoffRecord,
    AgentRun,
    AssistantConversation,
    AssistantEvent,
    AssistantJob,
    AssistantMessage,
    AssistantTurn,
    OrchestrationRun,
)
from app.modules.identity.domain.auth import AuthenticatedActor


@dataclass(frozen=True, slots=True)
class AssistantConversationMutationResult:
    conversation: AssistantConversation
    replayed: bool


@dataclass(frozen=True, slots=True)
class AssistantTurnMutationResult:
    message: AssistantMessage
    turn: AssistantTurn
    run: OrchestrationRun
    job: AssistantJob
    event: AssistantEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class AssistantConversationSnapshot:
    conversation: AssistantConversation
    messages: tuple[AssistantMessage, ...]
    turns: tuple[AssistantTurn, ...]
    orchestration_runs: tuple[OrchestrationRun, ...]
    events: tuple[AssistantEvent, ...]


class AssistantRepository(Protocol):
    async def create_conversation_mutation(
        self,
        *,
        actor: AuthenticatedActor,
        conversation: AssistantConversation,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> AssistantConversationMutationResult: ...

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
    ) -> AssistantTurnMutationResult: ...

    async def get_conversation_snapshot(
        self, *, actor: AuthenticatedActor, conversation_id: UUID
    ) -> AssistantConversationSnapshot | None: ...

    async def claim_job(
        self,
        *,
        organization_id: UUID,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> AssistantJob | None: ...

    async def begin_orchestration(self, *, job: AssistantJob) -> OrchestrationRun: ...

    async def append_agent_run(self, *, run: AgentRun) -> AgentRun: ...

    async def append_handoff(self, *, handoff: AgentHandoffRecord) -> None: ...

    async def save_checkpoint(self, *, checkpoint: AgentCheckpoint) -> None: ...

    async def append_event(self, *, event: AssistantEvent) -> AssistantEvent: ...

    async def complete_job(self, *, job_id: UUID, worker_id: str) -> None: ...

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        next_available_at: datetime,
    ) -> None: ...


class AssistantTransaction(Protocol):
    @property
    def repository(self) -> AssistantRepository: ...

    @property
    def session(self) -> Any: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def __aenter__(self) -> "AssistantTransaction": ...

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None: ...
