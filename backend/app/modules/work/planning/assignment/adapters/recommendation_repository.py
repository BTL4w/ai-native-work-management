"""Atomic PostgreSQL recommendation lifecycle; snapshots never authorize writes."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import cast
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.modules.audit.adapters.database_models import AuditEventModel
from app.modules.audit.domain.events import AuditOutcome
from app.modules.identity.adapters.database_models import UserModel
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.adapters.database_models import MembershipModel
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.adapters.database_models import (
    PersonSkillModel,
    SkillEvidenceModel,
    SkillModel,
)
from app.modules.people_capacity.adapters.repository import SqlAlchemyPeopleCapacityRepository
from app.modules.people_capacity.domain.workload import WorkloadInput
from app.modules.planning_runs.adapters.database_models import OutboxEventModel
from app.modules.work.adapters.database_models import (
    IdempotencyRecordModel,
    IdempotencyState,
    TaskModel,
)
from app.modules.work.planning.adapters.database_models import ProjectWeekModel
from app.modules.work.planning.assignment.adapters.recommendation_models import (
    CandidateScoreModel,
    ProjectTeamMembershipModel,
    RecommendationDecisionModel,
    RecommendationFeedbackModel,
    RecommendationModel,
    RecommendationSelectionModel,
    RecommendationVersionModel,
)
from app.modules.work.planning.assignment.adapters.repository import (
    SqlAlchemyTeamRequirementRepository,
)
from app.modules.work.planning.assignment.application.ranking_preview import RankingPreview
from app.modules.work.planning.assignment.application.recommendation_service import (
    CreateRecommendationCommand,
    DecideRecommendationCommand,
    RecommendationCommand,
    RecommendationResult,
    RecordFeedbackCommand,
    ReviseRecommendationCommand,
)
from app.modules.work.planning.assignment.application.requirement_service import (
    RequirementSet,
    TeamRequirementStatus,
)
from app.modules.work.planning.assignment.domain.recommendations import (
    CandidateOverride,
    RecommendationError,
    RecommendationStatus,
    RecommendationVersion,
    RequirementDemand,
    build_version,
)
from app.modules.work.planning.assignment.domain.team import (
    ProjectTeamMembership,
    RecommendationFeedback,
)

_VERSION = TypeAdapter(RecommendationVersion)
_FEEDBACK = TypeAdapter(RecommendationFeedback)


def fingerprint(command: RecommendationCommand) -> str:
    values = asdict(command)
    values.pop("actor")
    values.pop("request_id")
    values.pop("idempotency_key")
    if isinstance(command, ReviseRecommendationCommand):
        values["overrides"] = sorted(
            values["overrides"],
            key=lambda item: (str(item["requirement_id"]), str(item["selected_membership_id"])),
        )
        for item in values["overrides"]:
            item["override_reason"] = (item["override_reason"] or "").strip() or None
            if item["allocated_effort_hours"] is not None:
                item["allocated_effort_hours"] = str(item["allocated_effort_hours"].normalize())
    if isinstance(command, DecideRecommendationCommand):
        values["reason"] = (command.reason or "").strip() or None
    return sha256(
        json.dumps(values, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SqlAlchemyRecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._requirements = SqlAlchemyTeamRequirementRepository(session)

    async def _actor(self, actor: AuthenticatedActor, *, manage: bool) -> None:
        await self._requirements.activate_tenant(actor)
        active = await self._session.scalar(
            text("SELECT public.lock_active_membership(:organization_id, :membership_id)"),
            {"organization_id": actor.organization_id, "membership_id": actor.membership_id},
        )
        if active is None:
            raise RecommendationError("FORBIDDEN")
        row = (
            await self._session.execute(
                select(MembershipModel, UserModel)
                .join(UserModel, UserModel.id == MembershipModel.user_id)
                .where(
                    MembershipModel.organization_id == actor.organization_id,
                    MembershipModel.id == actor.membership_id,
                    MembershipModel.user_id == actor.user_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise RecommendationError("FORBIDDEN")
        member, user = row
        if not member.is_active or not user.is_active or member.role != actor.role:
            raise RecommendationError("FORBIDDEN")
        if manage and member.role not in {MembershipRole.MANAGER, MembershipRole.ADMIN}:
            raise RecommendationError("FORBIDDEN")

    async def _root(
        self, actor: AuthenticatedActor, recommendation_id: UUID, *, lock: bool = False
    ) -> RecommendationModel:
        query = select(RecommendationModel).where(
            RecommendationModel.organization_id == actor.organization_id,
            RecommendationModel.id == recommendation_id,
        )
        root = await self._session.scalar(query)
        if root is None:
            raise RecommendationError("RESOURCE_NOT_FOUND")
        await self._requirements.authorize_project(
            actor, root.project_id, lock=lock, require_manage=True
        )
        if lock:
            root = await self._session.scalar(
                query.with_for_update().execution_options(populate_existing=True)
            )
            assert root is not None
        return root

    async def _version(
        self, actor: AuthenticatedActor, root: RecommendationModel, version: int
    ) -> RecommendationVersionModel:
        result = await self._session.scalar(
            select(RecommendationVersionModel).where(
                RecommendationVersionModel.organization_id == actor.organization_id,
                RecommendationVersionModel.recommendation_id == root.id,
                RecommendationVersionModel.version == version,
            )
        )
        if result is None:
            raise RecommendationError("RESOURCE_NOT_FOUND")
        return result

    async def get(
        self, actor: AuthenticatedActor, recommendation_id: UUID, version: int | None = None
    ) -> RecommendationVersion:
        await self._actor(actor, manage=True)
        root = await self._root(actor, recommendation_id)
        row = await self._version(
            actor, root, version if version is not None else root.current_version
        )
        result = _VERSION.validate_python(row.snapshot)
        if version is None:
            result = replace(result, status=cast(RecommendationStatus, root.status))
            if root.status == "PROPOSED":
                try:
                    await self._confirmed(
                        actor,
                        root.project_id,
                        result.requirement_set_id,
                        result.requirement_version,
                        result.policy_version,
                    )
                    current = await self._preview(actor, root.project_id)
                    current_candidates = {
                        (candidate.requirement_id, candidate.membership_id): candidate
                        for candidate in current.candidates
                    }
                    persisted_candidates = {
                        (candidate.requirement_id, candidate.membership_id): candidate
                        for candidate in result.alternatives
                    }
                    for selection in result.selections:
                        key = (selection.requirement_id, selection.membership_id)
                        candidate = current_candidates.get(key)
                        if (
                            candidate is None
                            or not candidate.eligible
                            or candidate.hard_failure_codes
                            or candidate != persisted_candidates.get(key)
                        ):
                            raise RecommendationError("CANDIDATE_INELIGIBLE")
                except RecommendationError:
                    result = replace(result, status="STALE")
        return result

    async def team(
        self, actor: AuthenticatedActor, project_id: UUID
    ) -> tuple[ProjectTeamMembership, ...]:
        await self._actor(actor, manage=False)
        # Approved team members can inspect the team even before any task is assigned.
        own = await self._session.scalar(
            select(ProjectTeamMembershipModel.id).where(
                ProjectTeamMembershipModel.organization_id == actor.organization_id,
                ProjectTeamMembershipModel.project_id == project_id,
                ProjectTeamMembershipModel.membership_id == actor.membership_id,
                ProjectTeamMembershipModel.active.is_(True),
            )
        )
        if own is None:
            await self._requirements.authorize_project(actor, project_id, require_manage=False)
        rows = (
            await self._session.scalars(
                select(ProjectTeamMembershipModel)
                .where(
                    ProjectTeamMembershipModel.organization_id == actor.organization_id,
                    ProjectTeamMembershipModel.project_id == project_id,
                    ProjectTeamMembershipModel.active.is_(True),
                )
                .order_by(ProjectTeamMembershipModel.membership_id)
            )
        ).all()
        return tuple(
            ProjectTeamMembership(
                r.id, r.project_id, r.membership_id, r.decision_id, r.active, r.created_at
            )
            for r in rows
        )

    async def _confirmed(
        self, actor: AuthenticatedActor, project_id: UUID, set_id: UUID, version: int, policy: str
    ) -> RequirementSet:
        if policy != "ranking-v1":
            raise RecommendationError("STALE_POLICY")
        requirements = await self._requirements.get_for_project(actor=actor, project_id=project_id)
        if (
            requirements is None
            or requirements.id != set_id
            or requirements.version != version
            or requirements.status != TeamRequirementStatus.CONFIRMED
            or requirements.incomplete_items
        ):
            raise RecommendationError("STALE_REQUIREMENTS")
        stored = await self._requirements.stored_task_provenance(actor, set_id, version)
        current = await self._requirements.project_task_provenance(actor, project_id)
        if stored != current:
            raise RecommendationError("STALE_REQUIREMENTS")
        active_ids = set(
            (
                await self._session.scalars(
                    select(SkillModel.id).where(
                        SkillModel.organization_id == actor.organization_id,
                        SkillModel.active.is_(True),
                        SkillModel.id.in_({r.skill_id for r in requirements.items}),
                    )
                )
            ).all()
        )
        if active_ids != {r.skill_id for r in requirements.items}:
            raise RecommendationError("CANDIDATE_INELIGIBLE")
        return requirements

    async def _preview(self, actor: AuthenticatedActor, project_id: UUID) -> RankingPreview:
        preview = await self._requirements.get_ranking_preview(actor=actor, project_id=project_id)
        assert preview is not None
        return preview

    async def _snapshot_inputs(
        self, actor: AuthenticatedActor, requirements: RequirementSet
    ) -> dict[str, object]:
        weeks = (
            await self._session.scalars(
                select(ProjectWeekModel).where(
                    ProjectWeekModel.organization_id == actor.organization_id,
                    ProjectWeekModel.id.in_({r.project_week_id for r in requirements.items}),
                )
            )
        ).all()
        workloads: list[WorkloadInput] = []
        source = SqlAlchemyPeopleCapacityRepository(self._session)
        for start in sorted({w.start_date for w in weeks}):
            workloads.extend(
                await source.load_workload_inputs(actor=actor, week_start=start, membership_id=None)
            )
        skills = (
            await self._session.scalars(
                select(PersonSkillModel).where(
                    PersonSkillModel.organization_id == actor.organization_id,
                    PersonSkillModel.skill_id.in_({r.skill_id for r in requirements.items}),
                )
            )
        ).all()
        skills = sorted(skills, key=lambda item: str(item.id))
        skill_ids = {skill.id for skill in skills}
        evidence = (
            await self._session.scalars(
                select(SkillEvidenceModel)
                .where(
                    SkillEvidenceModel.organization_id == actor.organization_id,
                    SkillEvidenceModel.person_skill_id.in_(skill_ids),
                )
                .order_by(SkillEvidenceModel.id)
            )
        ).all()
        evidence_task_ids = {
            item.source_resource_id for item in evidence if item.source_resource_type == "task"
        }
        evidence_task_rows = (
            await self._session.execute(
                select(TaskModel.id, TaskModel.version).where(
                    TaskModel.organization_id == actor.organization_id,
                    TaskModel.id.in_(evidence_task_ids),
                )
            )
        ).all()
        evidence_task_versions: dict[UUID, int] = {row[0]: row[1] for row in evidence_task_rows}
        task_provenance = await self._requirements.stored_task_provenance(
            actor, requirements.id, requirements.version
        )
        activation_rows = (
            await self._session.execute(
                select(MembershipModel, UserModel)
                .join(UserModel, UserModel.id == MembershipModel.user_id)
                .where(MembershipModel.organization_id == actor.organization_id)
                .order_by(MembershipModel.id)
            )
        ).all()
        return {
            "schema_version": "1.0",
            "captured_at": datetime.now(UTC).isoformat(),
            "origin": "DETERMINISTIC",
            "verifier_version": "team-recommendation-v1",
            "model_version": None,
            "prompt_version": None,
            "policy": {"version": "ranking-v1", "weights": ["0.50", "0.30", "0.15", "0.05"]},
            "requirements": TypeAdapter(RequirementSet).dump_python(requirements, mode="json"),
            "task_provenance": [
                {"task_id": str(task_id), "task_version": version}
                for task_id, version in task_provenance
            ],
            "workload_inputs": TypeAdapter(list[WorkloadInput]).dump_python(
                sorted(
                    workloads,
                    key=lambda item: (str(item.project_week_id), str(item.membership_id)),
                ),
                mode="json",
            ),
            "person_skills": [
                {
                    "id": str(s.id),
                    "membership_id": str(s.membership_id),
                    "skill_id": str(s.skill_id),
                    "level": s.level,
                    "active": s.active,
                    "version": s.version,
                    "verified_at": s.verified_at.isoformat(),
                    "verified_by_membership_id": str(s.verified_by_membership_id),
                }
                for s in skills
            ],
            "candidate_activation": [
                {
                    "membership_id": str(membership.id),
                    "membership_active": membership.is_active,
                    "user_id": str(user.id),
                    "user_active": user.is_active,
                }
                for membership, user in activation_rows
            ],
            "skill_evidence": [
                {
                    "id": str(item.id),
                    "person_skill_id": str(item.person_skill_id),
                    "source_resource_type": item.source_resource_type,
                    "source_resource_id": str(item.source_resource_id),
                    "source_resource_version": evidence_task_versions.get(item.source_resource_id),
                    "occurred_at": item.occurred_at.isoformat(),
                }
                for item in evidence
            ],
        }

    async def _claim(
        self, command: RecommendationCommand
    ) -> tuple[IdempotencyRecordModel, RecommendationResult | None]:
        operation = "team_recommendation." + type(command).__name__
        actor = command.actor
        now = datetime.now(UTC)
        await self._session.execute(
            pg_insert(IdempotencyRecordModel)
            .values(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                operation=operation,
                idempotency_key=command.idempotency_key,
                request_fingerprint=fingerprint(command),
                state=IdempotencyState.IN_PROGRESS,
                expires_at=now + timedelta(hours=24),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "organization_id",
                    "actor_membership_id",
                    "operation",
                    "idempotency_key",
                ]
            )
        )
        record = await self._session.scalar(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.organization_id == actor.organization_id,
                IdempotencyRecordModel.actor_membership_id == actor.membership_id,
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.idempotency_key == command.idempotency_key,
            )
            .with_for_update()
        )
        assert record is not None
        if record.request_fingerprint != fingerprint(command):
            raise RecommendationError("IDEMPOTENCY_KEY_REUSED")
        if record.state == IdempotencyState.COMPLETED and record.response_body:
            adapter = _FEEDBACK if isinstance(command, RecordFeedbackCommand) else _VERSION
            return record, replace(adapter.validate_python(record.response_body), replayed=True)
        return record, None

    async def _write_version(
        self,
        command: RecommendationCommand,
        root: RecommendationModel,
        value: RecommendationVersion,
        requirements: RequirementSet,
    ) -> None:
        version_id = uuid4()
        self._session.add(
            RecommendationVersionModel(
                id=version_id,
                organization_id=command.actor.organization_id,
                recommendation_id=root.id,
                version=value.version,
                requirement_set_id=value.requirement_set_id,
                requirement_version=value.requirement_version,
                policy_version=value.policy_version,
                snapshot=_VERSION.dump_python(value, mode="json"),
                input_snapshot=await self._snapshot_inputs(command.actor, requirements),
                created_by_membership_id=command.actor.membership_id,
            )
        )
        await self._session.flush()
        for c in value.alternatives:
            self._session.add(
                CandidateScoreModel(
                    id=uuid4(),
                    organization_id=command.actor.organization_id,
                    recommendation_version_id=version_id,
                    requirement_id=c.requirement_id,
                    membership_id=c.membership_id,
                    snapshot=TypeAdapter(type(c)).dump_python(c, mode="json"),
                )
            )
        await self._session.flush()
        for selection in value.selections:
            self._session.add(
                RecommendationSelectionModel(
                    id=uuid4(),
                    organization_id=command.actor.organization_id,
                    recommendation_version_id=version_id,
                    requirement_id=selection.requirement_id,
                    membership_id=selection.membership_id,
                    allocated_effort_hours=selection.allocated_effort_hours,
                    warning_codes=list(selection.warning_codes),
                    override_reason=selection.override_reason,
                )
            )
        root.current_version = value.version

    async def execute(self, command: RecommendationCommand) -> RecommendationResult:
        actor = command.actor
        await self._requirements.activate_tenant(actor)
        await self._actor(actor, manage=True)
        root = None
        if isinstance(command, CreateRecommendationCommand):
            project_id = command.project_id
            await self._requirements.authorize_project(actor, project_id, lock=True)
        else:
            root = await self._root(actor, command.recommendation_id, lock=True)
            project_id = root.project_id
        record, replay = await self._claim(command)
        if replay is not None:
            return replay
        result: RecommendationResult
        if isinstance(command, RecordFeedbackCommand):
            assert root is not None
            version_row = await self._version(actor, root, command.version)
            if command.kind not in {"accept", "override", "reject"} or len(command.comment) > 2000:
                raise RecommendationError("INVALID_FEEDBACK")
            result = RecommendationFeedback(
                uuid4(), root.id, command.version, command.kind, command.comment
            )
            self._session.add(
                RecommendationFeedbackModel(
                    id=result.id,
                    organization_id=actor.organization_id,
                    recommendation_version_id=version_row.id,
                    actor_membership_id=actor.membership_id,
                    kind=command.kind,
                    comment=command.comment,
                )
            )
            action = "feedback_recorded"
        elif isinstance(command, CreateRecommendationCommand):
            requirements = await self._confirmed(
                actor,
                project_id,
                command.requirement_set_id,
                command.requirement_version,
                command.policy_version,
            )
            preview = await self._preview(actor, project_id)
            demands = tuple(
                RequirementDemand(r.id, r.project_week_id, Decimal(r.effort_hours))
                for r in requirements.items
            )
            result = build_version(recommendation_id=uuid4(), preview=preview, demands=demands)
            root = RecommendationModel(
                id=result.recommendation_id,
                organization_id=actor.organization_id,
                project_id=project_id,
                current_version=1,
                status="PROPOSED",
            )
            self._session.add(root)
            await self._session.flush()
            await self._write_version(command, root, result, requirements)
            action = "created"
        else:
            assert root is not None
            if root.current_version != command.expected_version:
                raise RecommendationError("RESOURCE_VERSION_MISMATCH", root.current_version)
            if root.status != "PROPOSED":
                raise RecommendationError("RECOMMENDATION_NOT_PROPOSED")
            version_row = await self._version(actor, root, root.current_version)
            base = _VERSION.validate_python(version_row.snapshot)
            if isinstance(command, ReviseRecommendationCommand):
                requirements = await self._confirmed(
                    actor,
                    project_id,
                    base.requirement_set_id,
                    base.requirement_version,
                    base.policy_version,
                )
                preview = await self._preview(actor, project_id)
                result = build_version(
                    recommendation_id=root.id,
                    preview=preview,
                    demands=base.demands,
                    base=base,
                    overrides=tuple(
                        sorted(
                            command.overrides,
                            key=lambda c: (str(c.requirement_id), str(c.selected_membership_id)),
                        )
                    ),
                )
                await self._write_version(command, root, result, requirements)
                action = "revised"
            else:
                if command.action not in {"approve", "reject"}:
                    raise RecommendationError("INVALID_DECISION")
                if command.reason and len(command.reason.strip()) > 500:
                    raise RecommendationError("INVALID_DECISION")
                if command.action == "approve":
                    await self._confirmed(
                        actor,
                        project_id,
                        base.requirement_set_id,
                        base.requirement_version,
                        base.policy_version,
                    )
                    for membership_id in sorted({s.membership_id for s in base.selections}):
                        active = await self._session.scalar(
                            text(
                                "SELECT public.lock_active_membership"
                                "(:organization_id, :membership_id)"
                            ),
                            {
                                "organization_id": actor.organization_id,
                                "membership_id": membership_id,
                            },
                        )
                        if active is None:
                            raise RecommendationError("CANDIDATE_INELIGIBLE")
                    current = await self._preview(actor, project_id)
                    # Re-run every selection against current eligibility, not the persisted flags.
                    build_version(
                        recommendation_id=root.id,
                        preview=current,
                        demands=base.demands,
                        overrides=tuple(
                            CandidateOverride(
                                s.requirement_id,
                                s.membership_id,
                                s.override_reason,
                                s.allocated_effort_hours,
                            )
                            for s in base.selections
                        ),
                        enforce_manual_override_reasons=False,
                    )
                before = await self._task_assignees(actor, project_id)
                decision_id = uuid4()
                self._session.add(
                    RecommendationDecisionModel(
                        id=decision_id,
                        organization_id=actor.organization_id,
                        recommendation_version_id=version_row.id,
                        project_id=project_id,
                        actor_membership_id=actor.membership_id,
                        action=command.action,
                        reason=(command.reason or "").strip() or None,
                    )
                )
                await self._session.flush()
                if command.action == "approve":
                    for membership_id in sorted({s.membership_id for s in base.selections}):
                        await self._session.execute(
                            pg_insert(ProjectTeamMembershipModel)
                            .values(
                                id=uuid4(),
                                organization_id=actor.organization_id,
                                project_id=project_id,
                                membership_id=membership_id,
                                decision_id=decision_id,
                                recommendation_version_id=version_row.id,
                                decision_action="approve",
                                active=True,
                            )
                            .on_conflict_do_nothing(
                                index_elements=["organization_id", "project_id", "membership_id"],
                                index_where=text("active"),
                            )
                        )
                if before != await self._task_assignees(actor, project_id):
                    raise RuntimeError("Team approval must not change Task assignees")
                result = replace(
                    base, status="APPROVED" if command.action == "approve" else "REJECTED"
                )
                root.status = result.status
                action = "approved" if command.action == "approve" else "rejected"
        assert root is not None
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201 if action in {"created", "feedback_recorded"} else 200
        record.response_body = (
            _FEEDBACK.dump_python(result, mode="json")
            if isinstance(result, RecommendationFeedback)
            else _VERSION.dump_python(result, mode="json")
        )
        self._evidence(command, root.id, result.version, action)
        await self._session.flush()
        return result

    async def _task_assignees(
        self, actor: AuthenticatedActor, project_id: UUID
    ) -> tuple[tuple[UUID, UUID | None], ...]:
        rows = await self._session.execute(
            select(TaskModel.id, TaskModel.assignee_membership_id)
            .where(
                TaskModel.organization_id == actor.organization_id,
                TaskModel.project_id == project_id,
            )
            .order_by(TaskModel.id)
        )
        return tuple((row[0], row[1]) for row in rows)

    def _evidence(
        self, command: RecommendationCommand, recommendation_id: UUID, version: int, action: str
    ) -> None:
        actor = command.actor
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action="team_recommendation." + action,
                outcome=AuditOutcome.SUCCEEDED,
                resource_type="team_recommendation",
                resource_id=recommendation_id,
                request_id=command.request_id,
                idempotency_key=command.idempotency_key,
                before_data={},
                after_data={"recommendation_id": str(recommendation_id), "version": version},
                reason_data={},
            )
        )
        now, event_id = datetime.now(UTC), uuid4()
        self._session.add(
            OutboxEventModel(
                id=event_id,
                event_id=event_id,
                organization_id=actor.organization_id,
                event_type=f"team_recommendation.{action}.v1",
                aggregate_type="team_recommendation",
                aggregate_id=recommendation_id,
                payload={
                    "envelope_version": "1.0",
                    "organization_id": str(actor.organization_id),
                    "recommendation_id": str(recommendation_id),
                    "version": version,
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
        await self._requirements.activate_tenant(actor)
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=AuditOutcome.REJECTED,
                resource_type="team_recommendation",
                resource_id=resource_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data={},
                after_data={},
                reason_data={"code": reason_code},
            )
        )


class SqlAlchemyRecommendationTransactionFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[SqlAlchemyRecommendationRepository]:
        async with self._session_factory() as session:
            bind = session.bind
            if not isinstance(bind, AsyncConnection) or not bind.in_transaction():
                await session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
            try:
                yield SqlAlchemyRecommendationRepository(session)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
