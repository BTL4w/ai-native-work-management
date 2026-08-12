"""Runtime-facing adapter for safe current-actor resolution."""

from uuid import UUID

from app.modules.identity.application.current_actor_service import CurrentActorService
from app.modules.identity.domain.auth import AuthenticatedActor


class CurrentActorResolver:
    def __init__(self, service: CurrentActorService) -> None:
        self._service = service

    async def resolve(
        self, *, organization_id: UUID, membership_id: UUID
    ) -> AuthenticatedActor | None:
        return await self._service.resolve(
            organization_id=organization_id, membership_id=membership_id
        )
