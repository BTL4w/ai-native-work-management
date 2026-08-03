"""Authorization, validation, fingerprinting, and transactions for manual planning."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.application.manual_ports import (
    ManualPlanningTransactionFactory,
    PlanningDeleteResult,
    PlanningMutationResult,
    PlanningPage,
)
from app.modules.work.planning.domain.acceptance_criteria import (
    AcceptanceCriterion,
    AcceptanceCriterionDraft,
    AcceptanceCriterionPatch,
)
from app.modules.work.planning.domain.dependencies import (
    TaskDependency,
    TaskDependencyDraft,
    TaskDependencyPatch,
)
from app.modules.work.planning.domain.goals import Goal, GoalDraft, GoalPatch
from app.modules.work.planning.domain.milestones import (
    Milestone,
    MilestoneDraft,
    MilestonePatch,
)

_WRITERS = frozenset({MembershipRole.ADMIN, MembershipRole.MANAGER})


class PlanningError(Exception):
    """Base class for expected manual planning failures."""


class PlanningForbiddenError(PlanningError):
    """The actor cannot perform a planning mutation."""


class PlanningNotFoundError(PlanningError):
    """The resource is absent or invisible in the actor's tenant."""


class PlanningVersionMismatchError(PlanningError):
    def __init__(self, current_version: int) -> None:
        super().__init__(current_version)
        self.current_version = current_version


class PlanningIdempotencyKeyReusedError(PlanningError):
    """An idempotency key was reused for a different normalized request."""


class PlanningReferenceError(PlanningError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class GoalAlreadyExistsError(PlanningError):
    """A Project already owns its single Goal."""


class CrossProjectDependencyError(PlanningError):
    """Both dependency endpoints must belong to one Project."""


class DuplicateDependencyError(PlanningError):
    """The same directed dependency edge already exists."""


class DependencyCycleError(PlanningError):
    """Adding or changing an edge would create a cycle."""


class MilestoneDateInvariantError(PlanningError):
    """A Task due date would be later than its Milestone target date."""


class DuplicateAcceptanceCriterionError(PlanningError):
    """Criterion text must be unique after normalization within a Task."""


def _fingerprint(operation: str, values: dict[str, object]) -> str:
    canonical = json.dumps(
        {"operation": operation, "values": values},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class ManualPlanningService:
    def __init__(self, transaction_factory: ManualPlanningTransactionFactory) -> None:
        self._transactions = transaction_factory

    async def _require_writer(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str,
        resource_id: UUID | None = None,
    ) -> None:
        if actor.role in _WRITERS:
            return
        async with self._transactions() as repository:
            await repository.audit_rejection(
                actor=actor,
                action=action,
                request_id=request_id,
                reason_code="FORBIDDEN",
                idempotency_key=idempotency_key,
                resource_id=resource_id,
            )
        raise PlanningForbiddenError

    async def _audit_error(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str,
        resource_id: UUID | None,
        error: Exception,
    ) -> None:
        async with self._transactions() as repository:
            await repository.audit_rejection(
                actor=actor,
                action=action,
                request_id=request_id,
                reason_code=type(error).__name__,
                idempotency_key=idempotency_key,
                resource_id=resource_id,
            )

    async def list_goals(
        self, *, actor: AuthenticatedActor, project_id: UUID | None, page: int, page_size: int
    ) -> PlanningPage:
        async with self._transactions() as repository:
            return await repository.list_goals(
                actor=actor, project_id=project_id, page=page, page_size=page_size
            )

    async def get_goal(self, *, actor: AuthenticatedActor, goal_id: UUID) -> Goal:
        async with self._transactions() as repository:
            resource = await repository.get_goal(actor=actor, goal_id=goal_id)
        if resource is None:
            raise PlanningNotFoundError
        return resource

    async def list_milestones(
        self, *, actor: AuthenticatedActor, project_id: UUID | None, page: int, page_size: int
    ) -> PlanningPage:
        async with self._transactions() as repository:
            return await repository.list_milestones(
                actor=actor, project_id=project_id, page=page, page_size=page_size
            )

    async def get_milestone(self, *, actor: AuthenticatedActor, milestone_id: UUID) -> Milestone:
        async with self._transactions() as repository:
            resource = await repository.get_milestone(actor=actor, milestone_id=milestone_id)
        if resource is None:
            raise PlanningNotFoundError
        return resource

    async def list_dependencies(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID | None,
        task_id: UUID | None,
        page: int,
        page_size: int,
    ) -> PlanningPage:
        async with self._transactions() as repository:
            return await repository.list_dependencies(
                actor=actor, project_id=project_id, task_id=task_id, page=page, page_size=page_size
            )

    async def get_dependency(
        self, *, actor: AuthenticatedActor, dependency_id: UUID
    ) -> TaskDependency:
        async with self._transactions() as repository:
            resource = await repository.get_dependency(actor=actor, dependency_id=dependency_id)
        if resource is None:
            raise PlanningNotFoundError
        return resource

    async def list_acceptance_criteria(
        self, *, actor: AuthenticatedActor, task_id: UUID | None, page: int, page_size: int
    ) -> PlanningPage:
        async with self._transactions() as repository:
            return await repository.list_acceptance_criteria(
                actor=actor, task_id=task_id, page=page, page_size=page_size
            )

    async def get_acceptance_criterion(
        self, *, actor: AuthenticatedActor, criterion_id: UUID
    ) -> AcceptanceCriterion:
        async with self._transactions() as repository:
            resource = await repository.get_acceptance_criterion(
                actor=actor, criterion_id=criterion_id
            )
        if resource is None:
            raise PlanningNotFoundError
        return resource

    async def _delete_goal(
        self,
        *,
        actor: AuthenticatedActor,
        goal_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult:
        async with self._transactions() as repository:
            return await repository.delete_goal(
                actor=actor,
                goal_id=goal_id,
                expected_version=expected_version,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )

    async def _delete_milestone(
        self,
        *,
        actor: AuthenticatedActor,
        milestone_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult:
        async with self._transactions() as repository:
            return await repository.delete_milestone(
                actor=actor,
                milestone_id=milestone_id,
                expected_version=expected_version,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )

    async def _delete_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        dependency_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult:
        async with self._transactions() as repository:
            return await repository.delete_dependency(
                actor=actor,
                dependency_id=dependency_id,
                expected_version=expected_version,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )

    async def _delete_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        criterion_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult:
        async with self._transactions() as repository:
            return await repository.delete_acceptance_criterion(
                actor=actor,
                criterion_id=criterion_id,
                expected_version=expected_version,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )

    async def _authorized_delete(
        self,
        *,
        actor: AuthenticatedActor,
        kind: str,
        resource_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningDeleteResult:
        action = f"{kind}.deleted"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            resource_id=resource_id,
        )
        fingerprint = _fingerprint(
            f"{kind}.delete", {"resource_id": resource_id, "expected_version": expected_version}
        )
        try:
            if kind == "goal":
                return await self._delete_goal(
                    actor=actor,
                    goal_id=resource_id,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
            if kind == "milestone":
                return await self._delete_milestone(
                    actor=actor,
                    milestone_id=resource_id,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
            if kind == "task_dependency":
                return await self._delete_dependency(
                    actor=actor,
                    dependency_id=resource_id,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
            return await self._delete_criterion(
                actor=actor,
                criterion_id=resource_id,
                expected_version=expected_version,
                request_id=request_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=resource_id,
                error=error,
            )
            raise

    async def delete_goal(
        self,
        *,
        actor: AuthenticatedActor,
        goal_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningDeleteResult:
        return await self._authorized_delete(
            actor=actor,
            kind="goal",
            resource_id=goal_id,
            expected_version=expected_version,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    async def delete_milestone(
        self,
        *,
        actor: AuthenticatedActor,
        milestone_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningDeleteResult:
        return await self._authorized_delete(
            actor=actor,
            kind="milestone",
            resource_id=milestone_id,
            expected_version=expected_version,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    async def delete_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        dependency_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningDeleteResult:
        return await self._authorized_delete(
            actor=actor,
            kind="task_dependency",
            resource_id=dependency_id,
            expected_version=expected_version,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    async def delete_acceptance_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        criterion_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningDeleteResult:
        return await self._authorized_delete(
            actor=actor,
            kind="acceptance_criterion",
            resource_id=criterion_id,
            expected_version=expected_version,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    async def create_goal(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        title: str,
        description: str | None,
        expected_outcomes: tuple[str, ...],
        target_date: date | None,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "goal.created"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        try:
            draft = GoalDraft.create(
                project_id=project_id,
                title=title,
                description=description,
                expected_outcomes=expected_outcomes,
                target_date=target_date,
            )
            async with self._transactions() as repository:
                return await repository.create_goal(
                    actor=actor,
                    draft=draft,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_fingerprint(
                        "goal.create",
                        {
                            "project_id": project_id,
                            "title": draft.title,
                            "description": draft.description,
                            "expected_outcomes": draft.expected_outcomes,
                            "target_date": target_date,
                        },
                    ),
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=None,
                error=error,
            )
            raise

    async def update_goal(
        self,
        *,
        actor: AuthenticatedActor,
        goal_id: UUID,
        title: str | None,
        title_supplied: bool,
        description: str | None,
        description_supplied: bool,
        expected_outcomes: tuple[str, ...],
        expected_outcomes_supplied: bool,
        target_date: date | None,
        target_date_supplied: bool,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "goal.updated"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            resource_id=goal_id,
        )
        try:
            patch = GoalPatch.create(
                title=title,
                title_supplied=title_supplied,
                description=description,
                description_supplied=description_supplied,
                expected_outcomes=expected_outcomes,
                expected_outcomes_supplied=expected_outcomes_supplied,
                target_date=target_date,
                target_date_supplied=target_date_supplied,
            )
            patch.validate_not_empty()
            fingerprint = _fingerprint(
                "goal.update",
                {
                    "goal_id": goal_id,
                    "title": patch.title if patch.title_supplied else "__omitted__",
                    "description": patch.description
                    if patch.description_supplied
                    else "__omitted__",
                    "expected_outcomes": patch.expected_outcomes
                    if patch.expected_outcomes_supplied
                    else "__omitted__",
                    "target_date": patch.target_date
                    if patch.target_date_supplied
                    else "__omitted__",
                    "expected_version": expected_version,
                },
            )
            async with self._transactions() as repository:
                return await repository.update_goal(
                    actor=actor,
                    goal_id=goal_id,
                    patch=patch,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=goal_id,
                error=error,
            )
            raise

    async def create_milestone(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        name: str,
        description: str | None,
        target_date: date | None,
        position: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "milestone.created"
        await self._require_writer(
            actor=actor, action=action, request_id=request_id, idempotency_key=idempotency_key
        )
        try:
            draft = MilestoneDraft.create(
                project_id=project_id,
                name=name,
                description=description,
                target_date=target_date,
                position=position,
            )
            fingerprint = _fingerprint(
                "milestone.create",
                {
                    "project_id": project_id,
                    "name": draft.name,
                    "description": draft.description,
                    "target_date": target_date,
                    "position": position,
                },
            )
            async with self._transactions() as repository:
                return await repository.create_milestone(
                    actor=actor,
                    draft=draft,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=None,
                error=error,
            )
            raise

    async def update_milestone(
        self,
        *,
        actor: AuthenticatedActor,
        milestone_id: UUID,
        name: str | None,
        name_supplied: bool,
        description: str | None,
        description_supplied: bool,
        target_date: date | None,
        target_date_supplied: bool,
        position: int | None,
        position_supplied: bool,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "milestone.updated"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            resource_id=milestone_id,
        )
        try:
            patch = MilestonePatch.create(
                name=name,
                name_supplied=name_supplied,
                description=description,
                description_supplied=description_supplied,
                target_date=target_date,
                target_date_supplied=target_date_supplied,
                position=position,
                position_supplied=position_supplied,
            )
            patch.validate_not_empty()
            async with self._transactions() as repository:
                return await repository.update_milestone(
                    actor=actor,
                    milestone_id=milestone_id,
                    patch=patch,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_fingerprint(
                        "milestone.update",
                        {
                            "milestone_id": milestone_id,
                            "name": patch.name if patch.name_supplied else "__omitted__",
                            "description": (
                                patch.description if patch.description_supplied else "__omitted__"
                            ),
                            "target_date": (
                                patch.target_date if patch.target_date_supplied else "__omitted__"
                            ),
                            "position": (
                                patch.position if patch.position_supplied else "__omitted__"
                            ),
                            "expected_version": expected_version,
                        },
                    ),
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=milestone_id,
                error=error,
            )
            raise

    async def create_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        predecessor_task_id: UUID,
        successor_task_id: UUID,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "task_dependency.created"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        try:
            draft = TaskDependencyDraft.create(
                predecessor_task_id=predecessor_task_id,
                successor_task_id=successor_task_id,
            )
            async with self._transactions() as repository:
                return await repository.create_dependency(
                    actor=actor,
                    draft=draft,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_fingerprint(
                        "task_dependency.create",
                        {
                            "predecessor_task_id": predecessor_task_id,
                            "successor_task_id": successor_task_id,
                        },
                    ),
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=None,
                error=error,
            )
            raise

    async def update_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        dependency_id: UUID,
        predecessor_task_id: UUID | None,
        predecessor_supplied: bool,
        successor_task_id: UUID | None,
        successor_supplied: bool,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "task_dependency.updated"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            resource_id=dependency_id,
        )
        try:
            patch = TaskDependencyPatch.create(
                predecessor_task_id=predecessor_task_id,
                predecessor_supplied=predecessor_supplied,
                successor_task_id=successor_task_id,
                successor_supplied=successor_supplied,
            )
            fingerprint = _fingerprint(
                "task_dependency.update",
                {
                    "dependency_id": dependency_id,
                    "predecessor_task_id": predecessor_task_id
                    if predecessor_supplied
                    else "__omitted__",
                    "successor_task_id": successor_task_id if successor_supplied else "__omitted__",
                    "expected_version": expected_version,
                },
            )
            async with self._transactions() as repository:
                return await repository.update_dependency(
                    actor=actor,
                    dependency_id=dependency_id,
                    patch=patch,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=dependency_id,
                error=error,
            )
            raise

    async def create_acceptance_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: UUID,
        text: str,
        position: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "acceptance_criterion.created"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        try:
            draft = AcceptanceCriterionDraft.create(
                task_id=task_id,
                text=text,
                position=position,
            )
            async with self._transactions() as repository:
                return await repository.create_acceptance_criterion(
                    actor=actor,
                    draft=draft,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_fingerprint(
                        "acceptance_criterion.create",
                        {"task_id": task_id, "text": draft.text, "position": position},
                    ),
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=None,
                error=error,
            )
            raise

    async def update_acceptance_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        criterion_id: UUID,
        text: str | None,
        text_supplied: bool,
        position: int | None,
        position_supplied: bool,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PlanningMutationResult:
        action = "acceptance_criterion.updated"
        await self._require_writer(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            resource_id=criterion_id,
        )
        try:
            patch = AcceptanceCriterionPatch.create(
                text=text,
                text_supplied=text_supplied,
                position=position,
                position_supplied=position_supplied,
            )
            patch.validate_not_empty()
            fingerprint = _fingerprint(
                "acceptance_criterion.update",
                {
                    "criterion_id": criterion_id,
                    "text": patch.text if patch.text_supplied else "__omitted__",
                    "position": patch.position if patch.position_supplied else "__omitted__",
                    "expected_version": expected_version,
                },
            )
            async with self._transactions() as repository:
                return await repository.update_acceptance_criterion(
                    actor=actor,
                    criterion_id=criterion_id,
                    patch=patch,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
        except Exception as error:
            await self._audit_error(
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=criterion_id,
                error=error,
            )
            raise
