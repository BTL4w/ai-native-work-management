"""Explicit assignment service authorization and transaction behavior."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.domain.tasks import Task, TaskStatus
from app.modules.work.planning.assignment.application.assignment_service import (
    AssignmentError,
    AssignmentWarning,
    ExplicitAssignmentCommand,
    ExplicitAssignmentResult,
    ExplicitTaskAssignmentService,
)


def actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Manager",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


def command(value: AuthenticatedActor) -> ExplicitAssignmentCommand:
    return ExplicitAssignmentCommand(
        actor=value,
        task_id=uuid4(),
        assignee_membership_id=uuid4(),
        expected_task_version=3,
        request_id="request-13",
        idempotency_key="explicit-assign-001",
    )


def task(value: ExplicitAssignmentCommand) -> Task:
    now = datetime.now(UTC)
    return Task(
        id=value.task_id,
        organization_id=value.actor.organization_id,
        project_id=uuid4(),
        project_week_id=uuid4(),
        milestone_id=None,
        title="Exact Task",
        description=None,
        assignee_membership_id=value.assignee_membership_id,
        assignee_display_name="Lan",
        required_skill_labels=("research",),
        estimated_effort_hours=8,
        status=TaskStatus.TO_DO,
        due_date=None,
        version=value.expected_task_version + 1,
        created_at=now,
        updated_at=now,
    )


def command_log() -> list[ExplicitAssignmentCommand]:
    return []


def rejection_log() -> list[tuple[str, UUID | None]]:
    return []


@dataclass
class RecordingRepository(AbstractAsyncContextManager["RecordingRepository"]):
    result: ExplicitAssignmentResult | None = None
    error: AssignmentError | None = None
    commands: list[ExplicitAssignmentCommand] = field(default_factory=command_log)
    rejected: list[tuple[str, UUID | None]] = field(default_factory=rejection_log)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def assign(self, command: ExplicitAssignmentCommand) -> ExplicitAssignmentResult:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

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
        self.rejected.append((reason_code, resource_id))


@pytest.mark.asyncio
async def test_overload_warns_but_does_not_replace_explicit_assignee() -> None:
    value = command(actor())
    expected = ExplicitAssignmentResult(
        task=task(value),
        warnings=(AssignmentWarning("ASSIGNEE_OVER_CAPACITY"),),
        effective_capacity_hours=4,
        workload_before_hours=4,
        workload_after_hours=12,
        replayed=False,
    )
    repository = RecordingRepository(result=expected)

    result = await ExplicitTaskAssignmentService(lambda: repository).assign(value)

    assert result.task.assignee_membership_id == value.assignee_membership_id
    assert result.warnings == (AssignmentWarning("ASSIGNEE_OVER_CAPACITY"),)
    assert repository.commands == [value]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [MembershipRole.MANAGER, MembershipRole.ADMIN])
async def test_manager_and_admin_use_the_exact_ids(role: MembershipRole) -> None:
    value = command(actor(role))
    expected = ExplicitAssignmentResult(task=task(value), replayed=False)
    repository = RecordingRepository(result=expected)

    await ExplicitTaskAssignmentService(lambda: repository).assign(value)

    assert repository.commands[0].task_id == value.task_id
    assert repository.commands[0].assignee_membership_id == value.assignee_membership_id


@pytest.mark.asyncio
async def test_employee_is_denied_before_assignment_and_rejection_is_audited() -> None:
    value = command(actor(MembershipRole.EMPLOYEE))
    repository = RecordingRepository()

    with pytest.raises(AssignmentError, match="FORBIDDEN"):
        await ExplicitTaskAssignmentService(lambda: repository).assign(value)

    assert repository.commands == []
    assert repository.rejected == [("FORBIDDEN", value.task_id)]


@pytest.mark.asyncio
async def test_policy_failure_rolls_back_assignment_transaction_and_is_audited_separately() -> None:
    value = command(actor())
    repository = RecordingRepository(error=AssignmentError("ASSIGNEE_NOT_ON_PROJECT_TEAM"))

    with pytest.raises(AssignmentError, match="ASSIGNEE_NOT_ON_PROJECT_TEAM"):
        await ExplicitTaskAssignmentService(lambda: repository).assign(value)

    assert repository.commands == [value]
    assert repository.rejected == [("ASSIGNEE_NOT_ON_PROJECT_TEAM", value.task_id)]
