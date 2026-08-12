"""Resolve a worker actor from durable identity state at execution time."""

from uuid import UUID

from app.modules.identity.application.ports import AuthTransactionFactory
from app.modules.identity.domain.auth import AuthenticatedActor


class CurrentActorService:
    def __init__(self, transaction_factory: AuthTransactionFactory) -> None:
        self._transactions = transaction_factory

    async def resolve(
        self, *, organization_id: UUID, membership_id: UUID
    ) -> AuthenticatedActor | None:
        async with self._transactions() as repository:
            actor = await repository.find_current_actor_by_membership(
                organization_id=organization_id, membership_id=membership_id
            )
        if actor is None:
            return None
        if actor.organization_id != organization_id or actor.membership_id != membership_id:
            return None
        return actor
