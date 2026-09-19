"""Application boundary for one explicit, team-gated Task assignment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.domain.tasks import Task, TaskError

if TYPE_CHECKING:
    from app.modules.work.planning.assignment.application.ports import (
        ExplicitAssignmentTransactionFactory,
    )


class AssignmentError(TaskError):
    """An expected explicit-assignment validation failed."""

    def __init__(self, code: str, *, current_version: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.current_version = current_version


@dataclass(frozen=True, slots=True)
class AssignmentPolicyFacts:
    organization_id: UUID
    assignee_organization_id: UUID | None
    membership_active: bool
    user_active: bool
    active_project_team_membership: bool
    hard_policy_allowed: bool


def validate_assignment_policy(facts: AssignmentPolicyFacts) -> None:
    """Validate hard constraints shared by all assignment entry points."""

    if facts.assignee_organization_id != facts.organization_id:
        raise AssignmentError("ASSIGNEE_OUTSIDE_ORGANIZATION")
    if not facts.membership_active or not facts.user_active:
        raise AssignmentError("ASSIGNEE_INACTIVE")
    if not facts.active_project_team_membership:
        raise AssignmentError("ASSIGNEE_NOT_ON_PROJECT_TEAM")
    if not facts.hard_policy_allowed:
        raise AssignmentError("ASSIGNMENT_POLICY_DENIED")


@dataclass(frozen=True, slots=True)
class AssignmentWarning:
    code: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplicitAssignmentCommand:
    actor: AuthenticatedActor
    task_id: UUID
    assignee_membership_id: UUID
    expected_task_version: int
    request_id: str
    idempotency_key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplicitAssignmentResult:
    task: Task
    warnings: tuple[AssignmentWarning, ...] = ()
    effective_capacity_hours: int = 0
    workload_before_hours: int = 0
    workload_after_hours: int = 0
    replayed: bool


class ExplicitTaskAssignmentService:
    def __init__(self, transaction_factory: ExplicitAssignmentTransactionFactory) -> None:
        self._transactions = transaction_factory

    async def assign(self, command: ExplicitAssignmentCommand) -> ExplicitAssignmentResult:
        """Validate exact Manager intent and commit one assignment transaction."""

        try:
            if command.actor.role not in {MembershipRole.ADMIN, MembershipRole.MANAGER}:
                raise AssignmentError("FORBIDDEN")
            async with self._transactions() as repository:
                return await repository.assign(command)
        except AssignmentError as error:
            async with self._transactions() as repository:
                await repository.audit_rejection(
                    actor=command.actor,
                    action="task.assignment.rejected",
                    request_id=command.request_id,
                    idempotency_key=command.idempotency_key,
                    resource_id=command.task_id,
                    reason_code=error.code,
                )
            raise

    async def audit_transport_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        reason_code: str,
    ) -> None:
        """Persist failures raised before a valid assignment command exists."""

        async with self._transactions() as repository:
            await repository.audit_rejection(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=None,
                reason_code=reason_code,
            )
