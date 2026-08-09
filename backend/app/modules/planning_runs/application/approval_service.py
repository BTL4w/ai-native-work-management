"""Authorization, normalization and transaction boundary for approval decisions."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.application.approval_ports import (
    ApprovalDecision,
    ApprovalDecisionResult,
)
from app.modules.planning_runs.application.ports import PlanningRuntimePort, PlanningRunTransaction
from app.modules.planning_runs.application.run_service import fingerprint
from app.modules.planning_runs.domain.models import (
    PlanningRunDomainError,
    PlanningRunForbiddenError,
    ProposalStaleError,
)

_DECISION_ROLES = frozenset({MembershipRole.ADMIN, MembershipRole.MANAGER})
_MAX_REASON_LENGTH = 1000


class ApprovalService:
    """Decide one exact proposal version without invoking an AI provider."""

    def __init__(
        self,
        *,
        transaction_factory: Callable[[AuthenticatedActor], PlanningRunTransaction],
        runtime: PlanningRuntimePort,
    ) -> None:
        self._transaction_factory = transaction_factory
        self._runtime = runtime

    async def _audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        approval_id: UUID,
        request_id: str,
        idempotency_key: str,
        reason_code: str,
    ) -> None:
        async with self._transaction_factory(actor) as transaction:
            await transaction.repository.audit_rejection(
                actor=actor,
                action="approval.decided",
                request_id=request_id,
                reason_code=reason_code,
                idempotency_key=idempotency_key,
                resource_id=approval_id,
            )

    async def decide(
        self,
        *,
        actor: AuthenticatedActor,
        approval_id: UUID,
        decision: ApprovalDecision,
        expected_proposal_version: int,
        reason: str | None,
        request_id: str,
        idempotency_key: str,
    ) -> ApprovalDecisionResult:
        if actor.role not in _DECISION_ROLES:
            await self._audit_rejection(
                actor=actor,
                approval_id=approval_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                reason_code="FORBIDDEN",
            )
            raise PlanningRunForbiddenError
        try:
            normalized_reason = reason.strip() if reason is not None else None
            normalized_reason = normalized_reason or None
            if normalized_reason is not None and len(normalized_reason) > _MAX_REASON_LENGTH:
                raise ValueError("decision reason is too long")
            request_fingerprint = fingerprint(
                "approval.decision",
                {
                    "approval_id": str(approval_id),
                    "proposal_version": expected_proposal_version,
                    "decision": decision.value,
                    "reason": normalized_reason,
                },
            )
            async with self._transaction_factory(actor) as transaction:
                return await transaction.repository.decide_approval_mutation(
                    actor=actor,
                    approval_id=approval_id,
                    decision=decision,
                    expected_proposal_version=expected_proposal_version,
                    reason=normalized_reason,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    runtime=self._runtime,
                )
        except ProposalStaleError:
            async with self._transaction_factory(actor) as transaction:
                await transaction.repository.mark_stale_decision_attempt(
                    actor=actor,
                    approval_id=approval_id,
                    expected_proposal_version=expected_proposal_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
            raise
        except (PlanningRunDomainError, ValueError) as error:
            await self._audit_rejection(
                actor=actor,
                approval_id=approval_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                reason_code=type(error).__name__,
            )
            raise
        except Exception:
            await self._audit_rejection(
                actor=actor,
                approval_id=approval_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                reason_code="INTERNAL_ERROR",
            )
            raise
