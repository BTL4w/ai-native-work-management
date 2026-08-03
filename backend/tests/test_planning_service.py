"""Manual planning application-service tests."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import date
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.application.manual_ports import (
    ManualPlanningTransactionFactory,
    PlanningMutationResult,
    PlanningResource,
)
from app.modules.work.planning.application.manual_service import (
    CrossProjectDependencyError,
    DependencyCycleError,
    DuplicateAcceptanceCriterionError,
    DuplicateDependencyError,
    GoalAlreadyExistsError,
    ManualPlanningService,
    MilestoneDateInvariantError,
    PlanningForbiddenError,
    PlanningVersionMismatchError,
)
from app.modules.work.planning.domain.acceptance_criteria import AcceptanceCriterionDraft
from app.modules.work.planning.domain.dependencies import TaskDependencyDraft
from app.modules.work.planning.domain.goals import GoalDraft
from app.modules.work.planning.domain.milestones import MilestonePatch


def actor(role: MembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="actor@example.test",
        display_name="Actor",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


class FakeManualPlanningTransaction(AbstractAsyncContextManager["FakeManualPlanningTransaction"]):
    def __init__(self) -> None:
        self.rejections: list[str] = []
        self.goal_error: Exception | None = None
        self.milestone_error: Exception | None = None
        self.dependency_error: Exception | None = None
        self.criterion_error: Exception | None = None
        self.validated_edge: tuple[UUID, UUID] | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def create_goal(
        self,
        *,
        actor: AuthenticatedActor,
        draft: GoalDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult:
        if self.goal_error is not None:
            raise self.goal_error
        return PlanningMutationResult(resource=cast(PlanningResource, draft), replayed=False)

    async def update_milestone(
        self,
        *,
        actor: AuthenticatedActor,
        milestone_id: UUID,
        patch: MilestonePatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult:
        if self.milestone_error is not None:
            raise self.milestone_error
        return PlanningMutationResult(resource=cast(PlanningResource, patch), replayed=False)

    async def validate_dependency_edge(
        self,
        *,
        actor: AuthenticatedActor,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
    ) -> None:
        self.validated_edge = (predecessor_task_id, successor_task_id)
        if self.dependency_error is not None:
            raise self.dependency_error

    async def create_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        draft: TaskDependencyDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult:
        await self.validate_dependency_edge(
            actor=actor,
            predecessor_task_id=draft.predecessor_task_id,
            successor_task_id=draft.successor_task_id,
        )
        return PlanningMutationResult(resource=cast(PlanningResource, draft), replayed=False)

    async def create_acceptance_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        draft: AcceptanceCriterionDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult:
        if self.criterion_error is not None:
            raise self.criterion_error
        return PlanningMutationResult(resource=cast(PlanningResource, draft), replayed=False)

    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        reason_code: str,
        idempotency_key: str | None = None,
        resource_id: UUID | None = None,
    ) -> None:
        self.rejections.append(f"{action}:{reason_code}")


def service_for(transaction: FakeManualPlanningTransaction) -> ManualPlanningService:
    factory = cast(ManualPlanningTransactionFactory, lambda: transaction)
    return ManualPlanningService(factory)


@pytest.mark.asyncio
async def test_employee_goal_write_is_rejected_and_audited() -> None:
    transaction = FakeManualPlanningTransaction()
    service = service_for(transaction)

    with pytest.raises(PlanningForbiddenError):
        await service.create_goal(
            actor=actor(MembershipRole.EMPLOYEE),
            project_id=uuid4(),
            title="Forbidden",
            description=None,
            expected_outcomes=(),
            target_date=None,
            request_id="req-1",
            idempotency_key="goal-create-key-1",
        )

    assert transaction.rejections == ["goal.created:FORBIDDEN"]


@pytest.mark.asyncio
async def test_second_goal_for_project_is_rejected_and_audited() -> None:
    transaction = FakeManualPlanningTransaction()
    transaction.goal_error = GoalAlreadyExistsError()
    service = service_for(transaction)

    with pytest.raises(GoalAlreadyExistsError):
        await service.create_goal(
            actor=actor(MembershipRole.MANAGER),
            project_id=uuid4(),
            title="Duplicate",
            description=None,
            expected_outcomes=(),
            target_date=None,
            request_id="req-2",
            idempotency_key="goal-create-key-2",
        )

    assert transaction.rejections == ["goal.created:GoalAlreadyExistsError"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "validation_error",
    [
        DuplicateDependencyError(),
        pytest.param(CrossProjectDependencyError(), id="cross-project"),
        pytest.param(DependencyCycleError(), id="cycle-a-b-c-a"),
    ],
)
async def test_dependency_validation_failure_is_audited(validation_error: Exception) -> None:
    predecessor, successor = uuid4(), uuid4()
    transaction = FakeManualPlanningTransaction()
    transaction.dependency_error = validation_error
    service = service_for(transaction)

    with pytest.raises(type(validation_error)):
        await service.create_dependency(
            actor=actor(MembershipRole.MANAGER),
            predecessor_task_id=predecessor,
            successor_task_id=successor,
            request_id="req-3",
            idempotency_key="dependency-create-key-1",
        )

    assert transaction.validated_edge == (predecessor, successor)
    assert transaction.rejections == [f"task_dependency.created:{type(validation_error).__name__}"]


@pytest.mark.asyncio
async def test_milestone_target_before_linked_task_due_date_is_rejected() -> None:
    transaction = FakeManualPlanningTransaction()
    transaction.milestone_error = MilestoneDateInvariantError()
    service = service_for(transaction)

    with pytest.raises(MilestoneDateInvariantError):
        await service.update_milestone(
            actor=actor(MembershipRole.ADMIN),
            milestone_id=uuid4(),
            name=None,
            name_supplied=False,
            description=None,
            description_supplied=False,
            target_date=date(2026, 8, 1),
            target_date_supplied=True,
            position=None,
            position_supplied=False,
            expected_version=2,
            request_id="req-4",
            idempotency_key="milestone-update-key-1",
        )

    assert transaction.rejections == ["milestone.updated:MilestoneDateInvariantError"]


@pytest.mark.asyncio
async def test_duplicate_normalized_acceptance_criterion_is_rejected() -> None:
    transaction = FakeManualPlanningTransaction()
    transaction.criterion_error = DuplicateAcceptanceCriterionError()
    service = service_for(transaction)

    with pytest.raises(DuplicateAcceptanceCriterionError):
        await service.create_acceptance_criterion(
            actor=actor(MembershipRole.MANAGER),
            task_id=uuid4(),
            text="  Approved invoice  ",
            position=1,
            request_id="req-5",
            idempotency_key="criterion-create-key-1",
        )

    assert transaction.rejections == [
        "acceptance_criterion.created:DuplicateAcceptanceCriterionError"
    ]


@pytest.mark.asyncio
async def test_stale_milestone_update_reports_current_version_and_is_audited() -> None:
    transaction = FakeManualPlanningTransaction()
    transaction.milestone_error = PlanningVersionMismatchError(4)
    service = service_for(transaction)

    with pytest.raises(PlanningVersionMismatchError) as error:
        await service.update_milestone(
            actor=actor(MembershipRole.MANAGER),
            milestone_id=uuid4(),
            name="Updated",
            name_supplied=True,
            description=None,
            description_supplied=False,
            target_date=None,
            target_date_supplied=False,
            position=None,
            position_supplied=False,
            expected_version=3,
            request_id="req-6",
            idempotency_key="milestone-update-key-2",
        )

    assert error.value.current_version == 4
    assert transaction.rejections == ["milestone.updated:PlanningVersionMismatchError"]
