"""PostgreSQL persistence for append-only Team Requirement snapshots."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.adapters.database_models import AuditEventModel
from app.modules.audit.domain.events import AuditOutcome
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.adapters.database_models import SkillModel
from app.modules.people_capacity.domain.skills import SkillLevel
from app.modules.planning_runs.adapters.database_models import OutboxEventModel
from app.modules.work.adapters.database_models import (
    IdempotencyRecordModel,
    IdempotencyState,
    ProjectModel,
    TaskModel,
)
from app.modules.work.domain.tasks import Task, TaskStatus
from app.modules.work.planning.adapters.database_models import ProjectWeekModel
from app.modules.work.planning.assignment.adapters.database_models import (
    TeamRequirementItemModel,
    TeamRequirementSetModel,
    TeamRequirementTaskSourceModel,
    TeamRequirementVersionModel,
)
from app.modules.work.planning.assignment.application.requirement_service import (
    ConfirmRequirementsCommand,
    DeriveRequirementsCommand,
    IncompleteRequirementItem,
    RequirementCommand,
    RequirementItem,
    RequirementItemInput,
    RequirementSet,
    ReviseRequirementsCommand,
    TaskProvenance,
    TeamRequirementForbiddenError,
    TeamRequirementIdempotencyKeyReusedError,
    TeamRequirementIncompleteError,
    TeamRequirementNotFoundError,
    TeamRequirementReferenceError,
    TeamRequirementStatus,
    TeamRequirementVersionMismatchError,
    canonical_requirement_command,
    canonical_task_provenance,
)
from app.modules.work.planning.assignment.domain.requirements import (
    canonical_skill_label,
    derive_requirement_draft,
)

TEAM_REQUIREMENT_RLS_TABLES = (
    "team_requirement_sets",
    "team_requirement_versions",
    "team_requirement_items",
    "team_requirement_task_sources",
)
_TTL = timedelta(hours=24)


class SqlAlchemyTeamRequirementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _activate(self, actor: AuthenticatedActor) -> None:
        await self._session.execute(text("SET LOCAL ROLE app_runtime"))
        await self._session.execute(
            text("SELECT set_config('app.organization_id', :value, true)"),
            {"value": str(actor.organization_id)},
        )
        await self._session.execute(
            text("SELECT set_config('app.membership_id', :value, true)"),
            {"value": str(actor.membership_id)},
        )

    async def _project(
        self, actor: AuthenticatedActor, project_id: UUID, *, lock: bool = False
    ) -> ProjectModel:
        query = select(ProjectModel).where(
            ProjectModel.organization_id == actor.organization_id, ProjectModel.id == project_id
        )
        if lock:
            query = query.with_for_update()
        model = await self._session.scalar(query)
        if model is None:
            raise TeamRequirementNotFoundError
        if (
            actor.role is not MembershipRole.ADMIN
            and model.created_by_membership_id != actor.membership_id
        ):
            raise TeamRequirementForbiddenError
        return model

    def _audit(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        outcome: AuditOutcome,
        request_id: str,
        idempotency_key: str | None,
        resource_id: UUID | None,
        reason: str | None = None,
        after: dict[str, object] | None = None,
    ) -> None:
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=outcome,
                resource_type="team_requirement_set",
                resource_id=resource_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data={},
                after_data=after or {},
                reason_data={"code": reason} if reason else {},
            )
        )

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
        await self._activate(actor)
        self._audit(
            actor=actor,
            action=action,
            outcome=AuditOutcome.REJECTED,
            request_id=request_id,
            idempotency_key=idempotency_key,
            resource_id=resource_id,
            reason=reason_code,
        )

    @staticmethod
    def _fingerprint(command: RequirementCommand) -> str:
        return canonical_requirement_command(command)

    async def _claim(
        self, command: RequirementCommand, operation: str
    ) -> tuple[IdempotencyRecordModel, RequirementSet | None]:
        actor = command.actor
        key = command.idempotency_key
        fingerprint = self._fingerprint(command)
        now = datetime.now(UTC)
        inserted = await self._session.scalar(
            pg_insert(IdempotencyRecordModel)
            .values(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                operation=operation,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                state=IdempotencyState.IN_PROGRESS,
                response_status=None,
                response_body=None,
                expires_at=now + _TTL,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "organization_id",
                    "actor_membership_id",
                    "operation",
                    "idempotency_key",
                ]
            )
            .returning(IdempotencyRecordModel.id)
        )
        record = await self._session.scalar(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.organization_id == actor.organization_id,
                IdempotencyRecordModel.actor_membership_id == actor.membership_id,
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        if record is None:
            raise RuntimeError("idempotency record missing")
        if inserted is not None:
            return record, None
        if record.request_fingerprint != fingerprint:
            raise TeamRequirementIdempotencyKeyReusedError
        if record.state != IdempotencyState.COMPLETED or not record.response_body:
            raise TeamRequirementIdempotencyKeyReusedError
        result = await self._get_by_set(
            actor,
            UUID(str(record.response_body["id"])),
            version_number=int(record.response_body["version"]),
        )
        return record, result if result is None else replace(result, replayed=True)

    async def _validate_inputs(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        items: tuple[RequirementItemInput, ...],
    ) -> dict[UUID, int]:
        for item in items:
            skill = await self._session.scalar(
                select(SkillModel).where(
                    SkillModel.organization_id == actor.organization_id,
                    SkillModel.id == item.skill_id,
                    SkillModel.active.is_(True),
                )
            )
            if skill is None:
                raise TeamRequirementReferenceError("skill_id")
            week = await self._session.scalar(
                select(ProjectWeekModel.id).where(
                    ProjectWeekModel.organization_id == actor.organization_id,
                    ProjectWeekModel.id == item.project_week_id,
                    ProjectWeekModel.project_id == project_id,
                )
            )
            if week is None:
                raise TeamRequirementReferenceError("project_week_id")
            for task_id in item.source_task_ids:
                task = await self._session.scalar(
                    select(TaskModel).where(
                        TaskModel.organization_id == actor.organization_id,
                        TaskModel.id == task_id,
                        TaskModel.project_id == project_id,
                    )
                )
                if task is None:
                    raise TeamRequirementReferenceError("source_task_ids")
        versions: dict[UUID, int] = {}
        for task_id in {source for item in items for source in item.source_task_ids}:
            task = await self._session.scalar(
                select(TaskModel).where(
                    TaskModel.organization_id == actor.organization_id,
                    TaskModel.id == task_id,
                )
            )
            if task is None:
                raise TeamRequirementReferenceError("source_task_ids")
            versions[task_id] = task.version
        return versions

    async def _project_task_models(
        self,
        actor: AuthenticatedActor,
        project_id: UUID,
        *,
        lock: bool,
    ) -> tuple[TaskModel, ...]:
        query = select(TaskModel).where(
            TaskModel.organization_id == actor.organization_id,
            TaskModel.project_id == project_id,
        )
        if lock:
            query = query.with_for_update()
        models = (await self._session.scalars(query.order_by(TaskModel.id))).all()
        return tuple(models)

    async def _project_task_provenance(
        self, actor: AuthenticatedActor, project_id: UUID, *, lock: bool = True
    ) -> TaskProvenance:
        models = await self._project_task_models(actor, project_id, lock=lock)
        return canonical_task_provenance(tuple((model.id, model.version) for model in models))

    async def _derive_inputs(
        self, actor: AuthenticatedActor, project_id: UUID
    ) -> tuple[
        tuple[RequirementItemInput, ...],
        tuple[tuple[UUID, str], ...],
        TaskProvenance,
    ]:
        models = await self._project_task_models(actor, project_id, lock=True)
        provenance = canonical_task_provenance(tuple((model.id, model.version) for model in models))
        tasks = tuple(
            Task(
                id=m.id,
                organization_id=m.organization_id,
                project_id=m.project_id,
                milestone_id=m.milestone_id,
                title=m.title,
                description=m.description,
                assignee_membership_id=m.assignee_membership_id,
                assignee_display_name=None,
                status=TaskStatus(m.status),
                due_date=m.due_date,
                version=m.version,
                created_at=m.created_at,
                updated_at=m.updated_at,
                project_week_id=m.project_week_id,
                required_skill_labels=tuple(m.required_skill_labels),
                estimated_effort_hours=m.estimated_effort_hours,
            )
            for m in models
        )
        draft = derive_requirement_draft(tasks=tasks)
        incomplete = [(item.task_id, item.reason) for item in draft.incomplete_items]
        inputs: list[RequirementItemInput] = []
        for requirement in draft.requirements:
            skill = await self._session.scalar(
                select(SkillModel).where(
                    SkillModel.organization_id == actor.organization_id,
                    SkillModel.normalized_name == canonical_skill_label(requirement.skill_label),
                    SkillModel.active.is_(True),
                )
            )
            if skill is None:
                incomplete.extend(
                    (task_id, "SKILL_TAXONOMY_MISSING") for task_id in requirement.task_ids
                )
                continue
            if (
                requirement.required_effort_hours
                != requirement.required_effort_hours.to_integral_value()
            ):
                raise TeamRequirementReferenceError("effort_hours")
            inputs.append(
                RequirementItemInput(
                    skill.id,
                    requirement.minimum_level,
                    requirement.project_week_id,
                    int(requirement.required_effort_hours),
                    requirement.task_ids,
                )
            )
        return (
            tuple(inputs),
            tuple(sorted(set(incomplete), key=lambda value: (str(value[0]), value[1]))),
            provenance,
        )

    async def _stored_task_provenance(
        self,
        actor: AuthenticatedActor,
        requirement_set_id: UUID,
        version: int,
    ) -> TaskProvenance:
        snapshot = await self._session.scalar(
            select(TeamRequirementVersionModel).where(
                TeamRequirementVersionModel.organization_id == actor.organization_id,
                TeamRequirementVersionModel.requirement_set_id == requirement_set_id,
                TeamRequirementVersionModel.version == version,
            )
        )
        if snapshot is None:
            raise TeamRequirementNotFoundError
        return canonical_task_provenance(
            tuple(
                (UUID(str(value["task_id"])), int(value["task_version"]))
                for value in snapshot.task_provenance
            )
        )

    async def _validate_incomplete_items(
        self,
        *,
        actor: AuthenticatedActor,
        project_id: UUID,
        incomplete: tuple[tuple[UUID, str], ...],
    ) -> None:
        for task_id, _reason in incomplete:
            task = await self._session.scalar(
                select(TaskModel.id).where(
                    TaskModel.organization_id == actor.organization_id,
                    TaskModel.id == task_id,
                    TaskModel.project_id == project_id,
                )
            )
            if task is None:
                raise TeamRequirementReferenceError("incomplete_items.task_id")

    async def _write_version(
        self,
        *,
        actor: AuthenticatedActor,
        set_model: TeamRequirementSetModel,
        version: int,
        status: TeamRequirementStatus,
        items: tuple[RequirementItemInput, ...],
        incomplete: tuple[tuple[UUID, str], ...],
        task_provenance: TaskProvenance,
    ) -> RequirementSet:
        now = datetime.now(UTC)
        task_versions = await self._validate_inputs(
            actor=actor, project_id=set_model.project_id, items=items
        )
        await self._validate_incomplete_items(
            actor=actor, project_id=set_model.project_id, incomplete=incomplete
        )
        version_model = TeamRequirementVersionModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            requirement_set_id=set_model.id,
            project_id=set_model.project_id,
            version=version,
            status=status.value,
            incomplete_items=[
                {"task_id": str(task_id), "reason": reason} for task_id, reason in incomplete
            ],
            task_provenance=[
                {"task_id": str(task_id), "task_version": task_version}
                for task_id, task_version in task_provenance
            ],
            created_by_membership_id=actor.membership_id,
            created_at=now,
        )
        self._session.add(version_model)
        await self._session.flush()
        persisted_items: list[RequirementItem] = []
        for item in sorted(items, key=lambda item: (item.project_week_id, item.skill_id)):
            item_model = TeamRequirementItemModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                requirement_version_id=version_model.id,
                skill_id=item.skill_id,
                minimum_level=int(item.minimum_level),
                project_week_id=item.project_week_id,
                effort_hours=item.effort_hours,
                created_at=now,
            )
            self._session.add(item_model)
            for task_id in item.source_task_ids:
                self._session.add(
                    TeamRequirementTaskSourceModel(
                        id=uuid4(),
                        organization_id=actor.organization_id,
                        requirement_item_id=item_model.id,
                        task_id=task_id,
                        task_version=task_versions[task_id],
                        created_at=now,
                    )
                )
            persisted_items.append(
                RequirementItem(
                    item_model.id,
                    item.skill_id,
                    item.minimum_level,
                    item.project_week_id,
                    item.effort_hours,
                    item.source_task_ids,
                )
            )
        set_model.current_version = version
        set_model.status = status.value
        set_model.version = version
        set_model.updated_by_membership_id = actor.membership_id
        set_model.updated_at = now
        return RequirementSet(
            set_model.id,
            actor.organization_id,
            set_model.project_id,
            version,
            status,
            tuple(persisted_items),
            tuple(IncompleteRequirementItem(task, reason) for task, reason in incomplete),
            set_model.created_at or now,
            now,
        )

    async def _get_by_set(
        self,
        actor: AuthenticatedActor,
        set_id: UUID,
        *,
        version_number: int | None = None,
    ) -> RequirementSet | None:
        root = await self._session.scalar(
            select(TeamRequirementSetModel).where(
                TeamRequirementSetModel.organization_id == actor.organization_id,
                TeamRequirementSetModel.id == set_id,
            )
        )
        if root is None:
            return None
        selected_version = root.current_version if version_number is None else version_number
        if selected_version is None:
            return None
        version = await self._session.scalar(
            select(TeamRequirementVersionModel).where(
                TeamRequirementVersionModel.organization_id == actor.organization_id,
                TeamRequirementVersionModel.requirement_set_id == set_id,
                TeamRequirementVersionModel.version == selected_version,
            )
        )
        if version is None:
            return None
        rows = (
            await self._session.scalars(
                select(TeamRequirementItemModel)
                .where(
                    TeamRequirementItemModel.organization_id == actor.organization_id,
                    TeamRequirementItemModel.requirement_version_id == version.id,
                )
                .order_by(
                    TeamRequirementItemModel.project_week_id, TeamRequirementItemModel.skill_id
                )
            )
        ).all()
        items: list[RequirementItem] = []
        for row in rows:
            source_ids = tuple(
                (
                    await self._session.scalars(
                        select(TeamRequirementTaskSourceModel.task_id)
                        .where(
                            TeamRequirementTaskSourceModel.organization_id == actor.organization_id,
                            TeamRequirementTaskSourceModel.requirement_item_id == row.id,
                        )
                        .order_by(TeamRequirementTaskSourceModel.task_id)
                    )
                ).all()
            )
            items.append(
                RequirementItem(
                    row.id,
                    row.skill_id,
                    SkillLevel(row.minimum_level),
                    row.project_week_id,
                    row.effort_hours,
                    source_ids,
                )
            )
        incomplete = tuple(
            IncompleteRequirementItem(UUID(str(value["task_id"])), str(value["reason"]))
            for value in version.incomplete_items
        )
        return RequirementSet(
            root.id,
            root.organization_id,
            root.project_id,
            version.version,
            TeamRequirementStatus(version.status),
            tuple(items),
            incomplete,
            root.created_at,
            version.created_at,
        )

    async def derive(self, command: DeriveRequirementsCommand) -> RequirementSet:
        await self._activate(command.actor)
        await self._project(command.actor, command.project_id, lock=True)
        record, replay = await self._claim(command, "team_requirement.derive")
        if replay:
            return replay
        exists = await self._session.scalar(
            select(TeamRequirementSetModel.id).where(
                TeamRequirementSetModel.organization_id == command.actor.organization_id,
                TeamRequirementSetModel.project_id == command.project_id,
            )
        )
        if exists:
            raise TeamRequirementReferenceError("project_id")
        if command.items is not None and command.incomplete_items is not None:
            items, incomplete = command.items, command.incomplete_items
            task_provenance = await self._project_task_provenance(command.actor, command.project_id)
        else:
            items, incomplete, task_provenance = await self._derive_inputs(
                command.actor, command.project_id
            )
        now = datetime.now(UTC)
        root = TeamRequirementSetModel(
            id=uuid4(),
            organization_id=command.actor.organization_id,
            project_id=command.project_id,
            current_version=None,
            status=TeamRequirementStatus.DRAFT.value,
            version=1,
            created_by_membership_id=command.actor.membership_id,
            updated_by_membership_id=command.actor.membership_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(root)
        await self._session.flush()
        result = await self._write_version(
            actor=command.actor,
            set_model=root,
            version=1,
            status=TeamRequirementStatus.DRAFT,
            items=items or (),
            incomplete=incomplete or (),
            task_provenance=task_provenance,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201
        record.response_body = {"id": str(result.id), "version": result.version}
        self._audit(
            actor=command.actor,
            action="team_requirement.derived",
            outcome=AuditOutcome.SUCCEEDED,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            resource_id=result.id,
            after={"version": 1},
        )
        return result

    async def revise(self, command: ReviseRequirementsCommand) -> RequirementSet:
        await self._activate(command.actor)
        await self._project(command.actor, command.project_id, lock=True)
        record, replay = await self._claim(command, "team_requirement.revise")
        if replay:
            return replay
        root = await self._session.scalar(
            select(TeamRequirementSetModel)
            .where(
                TeamRequirementSetModel.organization_id == command.actor.organization_id,
                TeamRequirementSetModel.id == command.requirement_set_id,
                TeamRequirementSetModel.project_id == command.project_id,
            )
            .with_for_update()
        )
        if root is None:
            raise TeamRequirementNotFoundError
        if root.version != command.expected_version:
            raise TeamRequirementVersionMismatchError(root.version)
        task_provenance = await self._project_task_provenance(command.actor, command.project_id)
        result = await self._write_version(
            actor=command.actor,
            set_model=root,
            version=root.version + 1,
            status=TeamRequirementStatus.DRAFT,
            items=command.items,
            incomplete=command.incomplete_items,
            task_provenance=task_provenance,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = {"id": str(result.id), "version": result.version}
        self._audit(
            actor=command.actor,
            action="team_requirement.revised",
            outcome=AuditOutcome.SUCCEEDED,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            resource_id=result.id,
            after={"version": result.version},
        )
        return result

    async def confirm(self, command: ConfirmRequirementsCommand) -> RequirementSet:
        await self._activate(command.actor)
        await self._project(command.actor, command.project_id, lock=True)
        record, replay = await self._claim(command, "team_requirement.confirm")
        if replay:
            return replay
        root = await self._session.scalar(
            select(TeamRequirementSetModel)
            .where(
                TeamRequirementSetModel.organization_id == command.actor.organization_id,
                TeamRequirementSetModel.id == command.requirement_set_id,
                TeamRequirementSetModel.project_id == command.project_id,
            )
            .with_for_update()
        )
        if root is None:
            raise TeamRequirementNotFoundError
        if root.version != command.expected_version:
            raise TeamRequirementVersionMismatchError(root.version)
        current = await self._get_by_set(command.actor, command.requirement_set_id)
        if current is None:
            raise TeamRequirementNotFoundError
        if current.status is TeamRequirementStatus.STALE:
            raise TeamRequirementIncompleteError
        if current.incomplete_items:
            raise TeamRequirementIncompleteError
        stored_provenance = await self._stored_task_provenance(
            command.actor, command.requirement_set_id, current.version
        )
        current_provenance = await self._project_task_provenance(command.actor, command.project_id)
        changed = stored_provenance != current_provenance
        status = TeamRequirementStatus.STALE if changed else TeamRequirementStatus.CONFIRMED
        result = await self._write_version(
            actor=command.actor,
            set_model=root,
            version=current.version + 1,
            status=status,
            items=tuple(
                RequirementItemInput(
                    item.skill_id,
                    item.minimum_level,
                    item.project_week_id,
                    item.effort_hours,
                    item.source_task_ids,
                )
                for item in current.items
            ),
            incomplete=tuple((item.task_id, item.reason) for item in current.incomplete_items),
            task_provenance=current_provenance,
        )
        if changed:
            self._audit(
                actor=command.actor,
                action="team_requirement.staled",
                outcome=AuditOutcome.REJECTED,
                request_id=command.request_id,
                idempotency_key=command.idempotency_key,
                resource_id=result.id,
                reason="TASK_PROVENANCE_CHANGED",
                after={"version": result.version},
            )
            record.state = IdempotencyState.COMPLETED
            record.response_status = 200
            record.response_body = {"id": str(result.id), "version": result.version}
            return result
        outbox_id = uuid4()
        now = datetime.now(UTC)
        self._session.add(
            OutboxEventModel(
                id=outbox_id,
                event_id=outbox_id,
                organization_id=command.actor.organization_id,
                event_type="team_requirement.confirmed.v1",
                aggregate_type="team_requirement_set",
                aggregate_id=current.id,
                payload={
                    "envelope_version": "1.0",
                    "organization_id": str(command.actor.organization_id),
                    "requirement_set_id": str(current.id),
                    "version": result.version,
                },
                status="PENDING",
                envelope_version="1.0",
                attempt_count=0,
                max_attempts=3,
                available_at=now,
                occurred_at=now,
                created_at=now,
            )
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = {"id": str(result.id), "version": result.version}
        self._audit(
            actor=command.actor,
            action="team_requirement.confirmed",
            outcome=AuditOutcome.SUCCEEDED,
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            resource_id=result.id,
            after={"version": result.version},
        )
        return result

    async def get_for_project(
        self, *, actor: AuthenticatedActor, project_id: UUID
    ) -> RequirementSet | None:
        await self._activate(actor)
        await self._project(actor, project_id)
        set_id = await self._session.scalar(
            select(TeamRequirementSetModel.id).where(
                TeamRequirementSetModel.organization_id == actor.organization_id,
                TeamRequirementSetModel.project_id == project_id,
            )
        )
        return await self._get_by_set(actor, set_id) if set_id else None


class SqlAlchemyTeamRequirementTransactionFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[SqlAlchemyTeamRequirementRepository]:
        async with self._session_factory.begin() as session:
            yield SqlAlchemyTeamRequirementRepository(session)
