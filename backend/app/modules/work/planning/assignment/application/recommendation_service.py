"""Transaction and audit boundaries for the deterministic team lifecycle."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.assignment.application.requirement_service import (
    TeamRequirementError,
    TeamRequirementForbiddenError,
    TeamRequirementNotFoundError,
)
from app.modules.work.planning.assignment.domain.recommendations import (
    CandidateOverride,
    RecommendationError,
    RecommendationVersion,
)
from app.modules.work.planning.assignment.domain.team import (
    ProjectTeamMembership,
    RecommendationFeedback,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MutationCommand:
    actor: AuthenticatedActor
    request_id: str
    idempotency_key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateRecommendationCommand(MutationCommand):
    project_id: UUID
    requirement_set_id: UUID
    requirement_version: int
    policy_version: str = "ranking-v1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviseRecommendationCommand(MutationCommand):
    recommendation_id: UUID
    expected_version: int
    overrides: tuple[CandidateOverride, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DecideRecommendationCommand(MutationCommand):
    recommendation_id: UUID
    expected_version: int
    action: Literal["approve", "reject"]
    reason: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordFeedbackCommand(MutationCommand):
    recommendation_id: UUID
    version: int
    kind: Literal["accept", "override", "reject"]
    comment: str = ""


type RecommendationCommand = (
    CreateRecommendationCommand
    | ReviseRecommendationCommand
    | DecideRecommendationCommand
    | RecordFeedbackCommand
)
type RecommendationResult = RecommendationVersion | RecommendationFeedback


class RecommendationRepository(Protocol):
    async def execute(self, command: RecommendationCommand) -> RecommendationResult: ...
    async def get(
        self, actor: AuthenticatedActor, recommendation_id: UUID, version: int | None = None
    ) -> RecommendationVersion: ...
    async def team(
        self, actor: AuthenticatedActor, project_id: UUID
    ) -> tuple[ProjectTeamMembership, ...]: ...
    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        resource_id: UUID | None,
        reason_code: str,
    ) -> None: ...


class TeamRecommendationService:
    def __init__(
        self,
        transaction_factory: Callable[[], AbstractAsyncContextManager[RecommendationRepository]],
    ) -> None:
        self._transactions = transaction_factory

    async def audit_transport_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        reason_code: str,
    ) -> None:
        async with self._transactions() as repository:
            await repository.audit_rejection(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=None,
                reason_code=reason_code,
            )

    async def _execute(self, command: RecommendationCommand) -> RecommendationResult:
        try:
            if command.actor.role not in {MembershipRole.ADMIN, MembershipRole.MANAGER}:
                raise RecommendationError("FORBIDDEN")
            for attempt in range(3):
                try:
                    async with self._transactions() as repository:
                        return await repository.execute(command)
                except DBAPIError as error:
                    sqlstate = getattr(error.orig, "sqlstate", None)
                    if sqlstate not in {"40001", "40P01"}:
                        raise
                    if attempt == 2:
                        raise RecommendationError("CONCURRENT_MODIFICATION") from error
            raise AssertionError("bounded retry loop did not return or raise")
        except (RecommendationError, TeamRequirementError) as error:
            mapped = self._map(error)
            async with self._transactions() as repository:
                await repository.audit_rejection(
                    actor=command.actor,
                    action="team_recommendation.mutation.rejected",
                    request_id=command.request_id,
                    idempotency_key=command.idempotency_key,
                    resource_id=getattr(command, "recommendation_id", None),
                    reason_code=mapped.code,
                )
            raise mapped from error

    @staticmethod
    def _map(error: RecommendationError | TeamRequirementError) -> RecommendationError:
        if isinstance(error, RecommendationError):
            return error
        if isinstance(error, TeamRequirementForbiddenError):
            return RecommendationError("FORBIDDEN")
        if isinstance(error, TeamRequirementNotFoundError):
            return RecommendationError("RESOURCE_NOT_FOUND")
        return RecommendationError("STALE_REQUIREMENTS")

    async def create(self, command: CreateRecommendationCommand) -> RecommendationVersion:
        return cast(RecommendationVersion, await self._execute(command))

    async def revise(self, command: ReviseRecommendationCommand) -> RecommendationVersion:
        return cast(RecommendationVersion, await self._execute(command))

    async def decide(self, command: DecideRecommendationCommand) -> RecommendationVersion:
        return cast(RecommendationVersion, await self._execute(command))

    async def record_feedback(self, command: RecordFeedbackCommand) -> RecommendationFeedback:
        return cast(RecommendationFeedback, await self._execute(command))

    async def get(
        self, actor: AuthenticatedActor, recommendation_id: UUID, version: int | None = None
    ) -> RecommendationVersion:
        try:
            async with self._transactions() as repository:
                return await repository.get(actor, recommendation_id, version)
        except TeamRequirementError as error:
            raise self._map(error) from error

    async def team(
        self, actor: AuthenticatedActor, project_id: UUID
    ) -> tuple[ProjectTeamMembership, ...]:
        try:
            async with self._transactions() as repository:
                return await repository.team(actor, project_id)
        except TeamRequirementError as error:
            raise self._map(error) from error
