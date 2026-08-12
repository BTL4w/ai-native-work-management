"""Assistant-job execution boundary; all long-running calls happen after actor resolution."""

from typing import Protocol
from uuid import UUID

from app.modules.assistant.domain.models import AssistantJob
from app.modules.identity.domain.auth import AuthenticatedActor


class AssistantExecutionPort(Protocol):
    async def execute_job(self, *, job: AssistantJob, actor: AuthenticatedActor) -> None: ...


class CurrentActorResolverPort(Protocol):
    async def resolve(
        self, *, organization_id: UUID, membership_id: UUID
    ) -> AuthenticatedActor | None: ...


class AssistantExecutionError(RuntimeError):
    safe_error_code = "ACTOR_CONTEXT_UNAVAILABLE"


class AssistantExecutionService:
    def __init__(
        self, *, actor_resolver: CurrentActorResolverPort, runtime: AssistantExecutionPort
    ) -> None:
        self._actor_resolver = actor_resolver
        self._runtime = runtime

    async def execute(self, *, job: AssistantJob, worker_id: str) -> None:
        actor = await self._actor_resolver.resolve(
            organization_id=job.organization_id, membership_id=job.requester_membership_id
        )
        if actor is None or actor.organization_id != job.organization_id:
            raise AssistantExecutionError("ACTOR_CONTEXT_UNAVAILABLE")
        await self._runtime.execute_job(job=job, actor=actor)
