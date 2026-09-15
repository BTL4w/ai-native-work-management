"""Application service authorization, mapping, and rejection audit behavior."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.assignment.application.recommendation_service import (
    CreateRecommendationCommand,
    RecommendationCommand,
    RecommendationResult,
    TeamRecommendationService,
)
from app.modules.work.planning.assignment.domain.recommendations import (
    RecommendationError,
    RecommendationVersion,
)
from app.modules.work.planning.assignment.domain.team import ProjectTeamMembership


def actor(role: MembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="member@example.test",
        display_name="Member",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


def rejection_log() -> list[tuple[str, str]]:
    return []


class SerializationFailure(RuntimeError):
    sqlstate = "40001"


@dataclass
class RecordingRepository(AbstractAsyncContextManager["RecordingRepository"]):
    execute_error: Exception | None = None
    result: RecommendationResult | None = None
    serialization_failures: int = 0
    commit_serialization_failures: int = 0
    execute_count: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=rejection_log)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None and self.commit_serialization_failures:
            self.commit_serialization_failures -= 1
            raise DBAPIError("commit", {}, SerializationFailure(), False)
        return None

    async def execute(self, command: RecommendationCommand) -> RecommendationResult:
        self.execute_count += 1
        if self.serialization_failures:
            self.serialization_failures -= 1
            raise DBAPIError("statement", {}, SerializationFailure(), False)
        if self.execute_error:
            raise self.execute_error
        if self.result is not None:
            return self.result
        raise AssertionError("not configured")

    async def get(
        self,
        actor: AuthenticatedActor,
        recommendation_id: UUID,
        version: int | None = None,
    ) -> RecommendationVersion:
        raise AssertionError("not configured")

    async def team(
        self, actor: AuthenticatedActor, project_id: UUID
    ) -> tuple[ProjectTeamMembership, ...]:
        raise AssertionError("not configured")

    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        resource_id: UUID | None,
        reason_code: str,
    ) -> None:
        self.rejected.append((action, reason_code))


def command(member: AuthenticatedActor) -> CreateRecommendationCommand:
    return CreateRecommendationCommand(
        actor=member,
        request_id="request",
        idempotency_key="a" * 16,
        project_id=uuid4(),
        requirement_set_id=uuid4(),
        requirement_version=1,
    )


@pytest.mark.asyncio
async def test_employee_is_rejected_before_repository_execution_and_audited() -> None:
    repository = RecordingRepository()
    service = TeamRecommendationService(lambda: repository)

    with pytest.raises(RecommendationError, match="FORBIDDEN"):
        await service.create(command(actor(MembershipRole.EMPLOYEE)))

    assert repository.execute_count == 0
    assert repository.rejected == [("team_recommendation.mutation.rejected", "FORBIDDEN")]


@pytest.mark.asyncio
async def test_expected_domain_failure_is_audited_once() -> None:
    repository = RecordingRepository(execute_error=RecommendationError("STALE_REQUIREMENTS"))
    service = TeamRecommendationService(lambda: repository)

    with pytest.raises(RecommendationError, match="STALE_REQUIREMENTS"):
        await service.create(command(actor(MembershipRole.MANAGER)))

    assert repository.execute_count == 1
    assert repository.rejected == [("team_recommendation.mutation.rejected", "STALE_REQUIREMENTS")]


@pytest.mark.asyncio
async def test_serialization_failures_retry_with_a_fixed_bound() -> None:
    expected = RecommendationVersion(uuid4(), 1, uuid4(), 1, "ranking-v1", (), (), (), (), None)
    repository = RecordingRepository(result=expected, serialization_failures=2)
    service = TeamRecommendationService(lambda: repository)

    result = await service.create(command(actor(MembershipRole.MANAGER)))

    assert result == expected
    assert repository.execute_count == 3
    assert repository.rejected == []


@pytest.mark.asyncio
async def test_commit_time_serialization_failures_are_retried() -> None:
    expected = RecommendationVersion(uuid4(), 1, uuid4(), 1, "ranking-v1", (), (), (), (), None)
    repository = RecordingRepository(result=expected, commit_serialization_failures=2)
    service = TeamRecommendationService(lambda: repository)

    result = await service.create(command(actor(MembershipRole.MANAGER)))

    assert result == expected
    assert repository.execute_count == 3
    assert repository.rejected == []


@pytest.mark.asyncio
async def test_serialization_retry_exhaustion_is_audited_once() -> None:
    repository = RecordingRepository(serialization_failures=3)
    service = TeamRecommendationService(lambda: repository)

    with pytest.raises(RecommendationError, match="CONCURRENT_MODIFICATION"):
        await service.create(command(actor(MembershipRole.MANAGER)))

    assert repository.execute_count == 3
    assert repository.rejected == [
        ("team_recommendation.mutation.rejected", "CONCURRENT_MODIFICATION")
    ]
