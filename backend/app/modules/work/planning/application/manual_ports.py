"""Typed transaction port for manual planning use cases."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
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
from app.modules.work.planning.domain.project_weeks import (
    ProjectWeek,
    ProjectWeekDraft,
    ProjectWeekPatch,
)

type PlanningResource = Goal | Milestone | ProjectWeek | TaskDependency | AcceptanceCriterion
type PlanningDraft = (
    GoalDraft | MilestoneDraft | ProjectWeekDraft | TaskDependencyDraft | AcceptanceCriterionDraft
)
type PlanningPatch = (
    GoalPatch | MilestonePatch | ProjectWeekPatch | TaskDependencyPatch | AcceptanceCriterionPatch
)


@dataclass(frozen=True, slots=True)
class PlanningPage:
    items: tuple[PlanningResource, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class PlanningMutationResult:
    resource: PlanningResource
    replayed: bool


@dataclass(frozen=True, slots=True)
class PlanningDeleteResult:
    resource_id: UUID
    version: int
    replayed: bool


class ManualPlanningRepository(Protocol):
    async def list_project_weeks(
        self, *, actor: AuthenticatedActor, project_id: UUID, page: int, page_size: int
    ) -> PlanningPage: ...
    async def get_project_week(
        self, *, actor: AuthenticatedActor, project_id: UUID, project_week_id: UUID
    ) -> ProjectWeek | None: ...
    async def create_project_week(
        self,
        *,
        actor: AuthenticatedActor,
        draft: ProjectWeekDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def update_project_week(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        project_week_id: UUID,
        patch: ProjectWeekPatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def delete_project_week(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        project_week_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult: ...
    async def list_goals(
        self, *, actor: AuthenticatedActor, project_id: UUID | None, page: int, page_size: int
    ) -> PlanningPage: ...
    async def get_goal(self, *, actor: AuthenticatedActor, goal_id: UUID) -> Goal | None: ...
    async def create_goal(
        self,
        *,
        actor: AuthenticatedActor,
        draft: GoalDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def update_goal(
        self,
        *,
        actor: AuthenticatedActor,
        goal_id: UUID,
        patch: GoalPatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def delete_goal(
        self,
        *,
        actor: AuthenticatedActor,
        goal_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult: ...

    async def list_milestones(
        self, *, actor: AuthenticatedActor, project_id: UUID | None, page: int, page_size: int
    ) -> PlanningPage: ...
    async def get_milestone(
        self, *, actor: AuthenticatedActor, milestone_id: UUID
    ) -> Milestone | None: ...
    async def create_milestone(
        self,
        *,
        actor: AuthenticatedActor,
        draft: MilestoneDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
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
    ) -> PlanningMutationResult: ...
    async def delete_milestone(
        self,
        *,
        actor: AuthenticatedActor,
        milestone_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult: ...

    async def list_dependencies(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID | None,
        task_id: UUID | None,
        page: int,
        page_size: int,
    ) -> PlanningPage: ...
    async def get_dependency(
        self, *, actor: AuthenticatedActor, dependency_id: UUID
    ) -> TaskDependency | None: ...
    async def create_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        draft: TaskDependencyDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def update_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        dependency_id: UUID,
        patch: TaskDependencyPatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def delete_dependency(
        self,
        *,
        actor: AuthenticatedActor,
        dependency_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult: ...

    async def list_acceptance_criteria(
        self, *, actor: AuthenticatedActor, task_id: UUID | None, page: int, page_size: int
    ) -> PlanningPage: ...
    async def get_acceptance_criterion(
        self, *, actor: AuthenticatedActor, criterion_id: UUID
    ) -> AcceptanceCriterion | None: ...
    async def create_acceptance_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        draft: AcceptanceCriterionDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def update_acceptance_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        criterion_id: UUID,
        patch: AcceptanceCriterionPatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningMutationResult: ...
    async def delete_acceptance_criterion(
        self,
        *,
        actor: AuthenticatedActor,
        criterion_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PlanningDeleteResult: ...

    async def validate_dependency_edge(
        self, *, actor: AuthenticatedActor, predecessor_task_id: UUID, successor_task_id: UUID
    ) -> None: ...
    async def audit_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        reason_code: str,
        idempotency_key: str | None = None,
        resource_id: UUID | None = None,
    ) -> None: ...


ManualPlanningTransactionFactory = Callable[
    [], AbstractAsyncContextManager[ManualPlanningRepository]
]
