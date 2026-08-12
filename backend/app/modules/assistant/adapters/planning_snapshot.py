"""Read-only Planning proposal snapshot adapter for Assistant card validation."""

from collections.abc import Callable
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.planning_runs.application.ports import PlanningRunTransaction


class PostgreSQLPlanningSnapshot:
    """Hydrate proposal state through the existing tenant-scoped Planning port."""

    def __init__(
        self,
        transaction_factory: Callable[[AuthenticatedActor], PlanningRunTransaction],
    ) -> None:
        self._transactions = transaction_factory

    async def get_proposal_version(
        self,
        *,
        actor: AuthenticatedActor,
        proposal_id: UUID,
    ) -> int | None:
        async with self._transactions(actor) as transaction:
            proposal = await transaction.repository.get_proposal(
                actor=actor,
                proposal_id=proposal_id,
            )
            await transaction.commit()
        return proposal.current_version_number if proposal is not None else None
