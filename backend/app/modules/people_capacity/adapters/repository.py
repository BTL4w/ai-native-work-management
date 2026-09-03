"""SQLAlchemy People Skills persistence with RLS, idempotency, and safe audit."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.adapters.database_models import AuditEventModel
from app.modules.audit.domain.events import AuditOutcome
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.adapters.database_models import MembershipModel
from app.modules.people_capacity.adapters.database_models import (
    CapacityEntryModel,
    LeaveEntryModel,
    PersonSkillModel,
    SkillEvidenceModel,
    SkillModel,
    SkillVersionModel,
    WorkOutcomeEvidenceModel,
)
from app.modules.people_capacity.application.ports import (
    EvidenceSourceSnapshot,
    PeopleCapacityRepository,
    PeopleMutationResult,
)
from app.modules.people_capacity.domain.availability import (
    CapacityEntry,
    CapacityEntryDraft,
    CapacityKind,
    LeaveEntry,
    LeaveEntryDraft,
    OverlappingCapacityEntriesError,
    ensure_capacity_entry_does_not_overlap,
)
from app.modules.people_capacity.domain.skills import (
    PeopleSkillConflictError,
    PeopleSkillIdempotencyKeyReusedError,
    PeopleSkillNotFoundError,
    PeopleSkillVersionMismatchError,
    PersonSkillDraft,
    PersonSkillPatch,
    Skill,
    SkillDraft,
    SkillEvidence,
    SkillEvidenceType,
    SkillLevel,
    SkillPatch,
    VerifiedPersonSkill,
    WorkOutcomeEvidence,
    WorkOutcomeEvidenceDraft,
)
from app.modules.people_capacity.domain.workload import WorkloadInput
from app.modules.work.adapters.database_models import (
    IdempotencyRecordModel,
    IdempotencyState,
    TaskModel,
)
from app.modules.work.domain.tasks import TaskStatus
from app.modules.work.planning.adapters.database_models import ProjectWeekModel

_IDEMPOTENCY_TTL = timedelta(hours=24)


def _skill_to_domain(model: SkillModel) -> Skill:
    return Skill(
        id=model.id,
        organization_id=model.organization_id,
        name=model.name,
        normalized_name=model.normalized_name,
        description=model.description,
        active=model.active,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _skill_to_json(skill: Skill) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "organization_id": str(skill.organization_id),
        "name": skill.name,
        "normalized_name": skill.normalized_name,
        "description": skill.description,
        "active": skill.active,
        "version": skill.version,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
    }


def _skill_from_json(value: dict[str, Any]) -> Skill:
    return Skill(
        id=UUID(str(value["id"])),
        organization_id=UUID(str(value["organization_id"])),
        name=str(value["name"]),
        normalized_name=str(value["normalized_name"]),
        description=str(value["description"]) if value["description"] is not None else None,
        active=bool(value["active"]),
        version=int(value["version"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
    )


def _person_skill_to_domain(model: PersonSkillModel) -> VerifiedPersonSkill:
    return VerifiedPersonSkill(
        id=model.id,
        organization_id=model.organization_id,
        membership_id=model.membership_id,
        skill_id=model.skill_id,
        level=SkillLevel(model.level),
        verified_by_membership_id=model.verified_by_membership_id,
        verified_at=model.verified_at,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
        active=model.active,
    )


def _person_skill_to_json(person_skill: VerifiedPersonSkill) -> dict[str, Any]:
    return {
        "id": str(person_skill.id),
        "organization_id": str(person_skill.organization_id),
        "membership_id": str(person_skill.membership_id),
        "skill_id": str(person_skill.skill_id),
        "level": person_skill.level.value,
        "verified_by_membership_id": str(person_skill.verified_by_membership_id),
        "verified_at": person_skill.verified_at.isoformat(),
        "version": person_skill.version,
        "created_at": person_skill.created_at.isoformat(),
        "updated_at": person_skill.updated_at.isoformat(),
        "active": person_skill.active,
    }


def _person_skill_from_json(value: dict[str, Any]) -> VerifiedPersonSkill:
    return VerifiedPersonSkill(
        id=UUID(str(value["id"])),
        organization_id=UUID(str(value["organization_id"])),
        membership_id=UUID(str(value["membership_id"])),
        skill_id=UUID(str(value["skill_id"])),
        level=SkillLevel(int(value["level"])),
        verified_by_membership_id=UUID(str(value["verified_by_membership_id"])),
        verified_at=datetime.fromisoformat(str(value["verified_at"])),
        version=int(value["version"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
        active=bool(value["active"]),
    )


def _work_evidence_to_domain(model: WorkOutcomeEvidenceModel) -> WorkOutcomeEvidence:
    return WorkOutcomeEvidence(
        id=model.id,
        organization_id=model.organization_id,
        membership_id=model.membership_id,
        evidence_type=model.evidence_type,
        summary=model.summary,
        source_resource_type=model.source_resource_type,
        source_resource_id=model.source_resource_id,
        source_resource_version=model.source_resource_version,
        observed_at=model.observed_at,
        created_by_membership_id=model.created_by_membership_id,
        created_at=model.created_at,
    )


def _skill_evidence_to_domain(model: SkillEvidenceModel) -> SkillEvidence:
    return SkillEvidence(
        id=model.id,
        organization_id=model.organization_id,
        person_skill_id=model.person_skill_id,
        evidence_type=model.evidence_type,
        summary=model.summary,
        source_resource_type=model.source_resource_type,
        source_resource_id=model.source_resource_id,
        occurred_at=model.occurred_at,
        created_by_membership_id=model.created_by_membership_id,
        created_at=model.created_at,
    )


def _skill_evidence_to_json(evidence: SkillEvidence) -> dict[str, Any]:
    return {
        "id": str(evidence.id),
        "organization_id": str(evidence.organization_id),
        "person_skill_id": str(evidence.person_skill_id),
        "evidence_type": evidence.evidence_type.value,
        "summary": evidence.summary,
        "source_resource_type": evidence.source_resource_type,
        "source_resource_id": str(evidence.source_resource_id),
        "occurred_at": evidence.occurred_at.isoformat(),
        "created_by_membership_id": str(evidence.created_by_membership_id),
        "created_at": evidence.created_at.isoformat(),
    }


def _skill_evidence_from_json(value: dict[str, Any]) -> SkillEvidence:
    return SkillEvidence(
        id=UUID(str(value["id"])),
        organization_id=UUID(str(value["organization_id"])),
        person_skill_id=UUID(str(value["person_skill_id"])),
        evidence_type=SkillEvidenceType(str(value["evidence_type"])),
        summary=str(value["summary"]),
        source_resource_type=str(value["source_resource_type"]),
        source_resource_id=UUID(str(value["source_resource_id"])),
        occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
        created_by_membership_id=UUID(str(value["created_by_membership_id"])),
        created_at=datetime.fromisoformat(str(value["created_at"])),
    )


def _work_evidence_to_json(evidence: WorkOutcomeEvidence) -> dict[str, Any]:
    return {
        "id": str(evidence.id),
        "organization_id": str(evidence.organization_id),
        "membership_id": str(evidence.membership_id),
        "evidence_type": evidence.evidence_type.value,
        "summary": evidence.summary,
        "source_resource_type": evidence.source_resource_type,
        "source_resource_id": str(evidence.source_resource_id),
        "source_resource_version": evidence.source_resource_version,
        "observed_at": evidence.observed_at.isoformat(),
        "created_by_membership_id": str(evidence.created_by_membership_id),
        "created_at": evidence.created_at.isoformat(),
    }


def _work_evidence_from_json(value: dict[str, Any]) -> WorkOutcomeEvidence:
    return WorkOutcomeEvidence(
        id=UUID(str(value["id"])),
        organization_id=UUID(str(value["organization_id"])),
        membership_id=UUID(str(value["membership_id"])),
        evidence_type=SkillEvidenceType(str(value["evidence_type"])),
        summary=str(value["summary"]),
        source_resource_type=str(value["source_resource_type"]),
        source_resource_id=UUID(str(value["source_resource_id"])),
        source_resource_version=int(value["source_resource_version"]),
        observed_at=datetime.fromisoformat(str(value["observed_at"])),
        created_by_membership_id=UUID(str(value["created_by_membership_id"])),
        created_at=datetime.fromisoformat(str(value["created_at"])),
    )


def _capacity_to_domain(model: CapacityEntryModel) -> CapacityEntry:
    return CapacityEntry(
        id=model.id,
        organization_id=model.organization_id,
        membership_id=model.membership_id,
        kind=model.kind,
        hours=model.hours,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        week_start=model.week_start,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _capacity_to_json(entry: CapacityEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "organization_id": str(entry.organization_id),
        "membership_id": str(entry.membership_id),
        "kind": entry.kind.value,
        "hours": entry.hours,
        "effective_from": entry.effective_from.isoformat(),
        "effective_to": entry.effective_to.isoformat(),
        "week_start": entry.week_start.isoformat() if entry.week_start else None,
        "version": entry.version,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _capacity_from_json(value: dict[str, Any]) -> CapacityEntry:
    return CapacityEntry(
        id=UUID(str(value["id"])),
        organization_id=UUID(str(value["organization_id"])),
        membership_id=UUID(str(value["membership_id"])),
        kind=CapacityKind(str(value["kind"])),
        hours=int(value["hours"]),
        effective_from=date.fromisoformat(str(value["effective_from"])),
        effective_to=date.fromisoformat(str(value["effective_to"])),
        week_start=(
            date.fromisoformat(str(value["week_start"])) if value.get("week_start") else None
        ),
        version=int(value["version"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
    )


def _capacity_audit_data(entry: CapacityEntry) -> dict[str, object]:
    return {
        "membership_id": str(entry.membership_id),
        "kind": entry.kind.value,
        "hours": entry.hours,
        "effective_from": entry.effective_from.isoformat(),
        "effective_to": entry.effective_to.isoformat(),
        "week_start": entry.week_start.isoformat() if entry.week_start else None,
        "version": entry.version,
    }


def _leave_hours_in_range(model: LeaveEntryModel, start: date, end: date) -> int:
    """Allocate total leave hours evenly by inclusive day, preserving the total."""

    overlap_start = max(model.start_date, start)
    overlap_end = min(model.end_date, end)
    if overlap_end < overlap_start:
        return 0
    total_days = (model.end_date - model.start_date).days + 1
    overlap_days = (overlap_end - overlap_start).days + 1
    hours_per_day, remainder = divmod(model.unavailable_hours, total_days)
    remainder_end = model.start_date + timedelta(days=remainder - 1)
    remainder_days = 0
    if remainder and overlap_start <= remainder_end:
        remainder_days = (min(overlap_end, remainder_end) - overlap_start).days + 1
    return hours_per_day * overlap_days + remainder_days


def _leave_to_domain(model: LeaveEntryModel) -> LeaveEntry:
    return LeaveEntry(
        id=model.id,
        organization_id=model.organization_id,
        membership_id=model.membership_id,
        start_date=model.start_date,
        end_date=model.end_date,
        unavailable_hours=model.unavailable_hours,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _leave_to_json(entry: LeaveEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "organization_id": str(entry.organization_id),
        "membership_id": str(entry.membership_id),
        "start_date": entry.start_date.isoformat(),
        "end_date": entry.end_date.isoformat(),
        "unavailable_hours": entry.unavailable_hours,
        "version": entry.version,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _leave_from_json(value: dict[str, Any]) -> LeaveEntry:
    return LeaveEntry(
        id=UUID(str(value["id"])),
        organization_id=UUID(str(value["organization_id"])),
        membership_id=UUID(str(value["membership_id"])),
        start_date=date.fromisoformat(str(value["start_date"])),
        end_date=date.fromisoformat(str(value["end_date"])),
        unavailable_hours=int(value["unavailable_hours"]),
        version=int(value["version"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
    )


class SqlAlchemyPeopleCapacityRepository:
    """Implement People Skills operations inside one transaction-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _flush_or_conflict(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise PeopleSkillConflictError from error

    async def _activate_actor(self, actor: AuthenticatedActor) -> None:
        await self._session.execute(text("SET LOCAL ROLE app_runtime"))
        await self._session.execute(
            text("SELECT set_config('app.organization_id', :value, true)"),
            {"value": str(actor.organization_id)},
        )
        await self._session.execute(
            text("SELECT set_config('app.membership_id', :value, true)"),
            {"value": str(actor.membership_id)},
        )

    async def _claim_idempotency[T](
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        loader: Callable[[dict[str, Any]], T],
    ) -> tuple[IdempotencyRecordModel | None, PeopleMutationResult[T] | None]:
        record_id = uuid4()
        now = datetime.now(UTC)
        claimed_id = await self._session.scalar(
            postgresql_insert(IdempotencyRecordModel)
            .values(
                id=record_id,
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                state=IdempotencyState.IN_PROGRESS,
                response_status=None,
                response_body=None,
                expires_at=now + _IDEMPOTENCY_TTL,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecordModel.organization_id,
                    IdempotencyRecordModel.actor_membership_id,
                    IdempotencyRecordModel.operation,
                    IdempotencyRecordModel.idempotency_key,
                ]
            )
            .returning(IdempotencyRecordModel.id)
        )
        record = await self._session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.id == (claimed_id if claimed_id is not None else record_id)
            )
        )
        if claimed_id is not None:
            if record is None:
                raise RuntimeError("claimed idempotency record is not visible")
            return record, None

        record = await self._session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.organization_id == actor.organization_id,
                IdempotencyRecordModel.actor_membership_id == actor.membership_id,
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.idempotency_key == idempotency_key,
            )
        )
        if record is None:
            raise RuntimeError("conflicting idempotency record is not visible")
        if record.request_fingerprint != request_fingerprint:
            raise PeopleSkillIdempotencyKeyReusedError
        if record.state is not IdempotencyState.COMPLETED or record.response_body is None:
            raise PeopleSkillIdempotencyKeyReusedError
        return (
            None,
            PeopleMutationResult(
                resource=loader(record.response_body),
                replayed=True,
                evidence=tuple(
                    _skill_evidence_from_json(value)
                    for value in record.response_body.get("_evidence", [])
                ),
            ),
        )

    async def _get_idempotency_replay[T](
        self,
        *,
        actor: AuthenticatedActor,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        loader: Callable[[dict[str, Any]], T],
    ) -> PeopleMutationResult[T] | None:
        record = await self._session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.organization_id == actor.organization_id,
                IdempotencyRecordModel.actor_membership_id == actor.membership_id,
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.idempotency_key == idempotency_key,
            )
        )
        if record is None:
            return None
        if record.request_fingerprint != request_fingerprint:
            raise PeopleSkillIdempotencyKeyReusedError
        if record.state is not IdempotencyState.COMPLETED or record.response_body is None:
            raise PeopleSkillIdempotencyKeyReusedError
        return PeopleMutationResult(
            resource=loader(record.response_body),
            replayed=True,
            evidence=tuple(
                _skill_evidence_from_json(value)
                for value in record.response_body.get("_evidence", [])
            ),
        )

    def _audit_success(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        resource_type: str,
        resource_id: UUID,
        request_id: str,
        idempotency_key: str,
        before_data: dict[str, object],
        after_data: dict[str, object],
    ) -> None:
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=AuditOutcome.SUCCEEDED,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data=before_data,
                after_data=after_data,
                reason_data={},
            )
        )

    async def list_skills(self, *, actor: AuthenticatedActor) -> tuple[Skill, ...]:
        await self._activate_actor(actor)
        models = await self._session.scalars(
            select(SkillModel)
            .where(SkillModel.organization_id == actor.organization_id)
            .order_by(SkillModel.normalized_name, SkillModel.id)
        )
        return tuple(_skill_to_domain(model) for model in models)

    async def membership_is_active(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        for_update: bool = False,
    ) -> bool:
        await self._activate_actor(actor)
        if for_update:
            return bool(
                await self._session.scalar(
                    text("SELECT public.lock_active_membership(:organization_id, :membership_id)"),
                    {
                        "organization_id": actor.organization_id,
                        "membership_id": membership_id,
                    },
                )
            )
        return bool(
            await self._session.scalar(
                select(MembershipModel.is_active).where(
                    MembershipModel.organization_id == actor.organization_id,
                    MembershipModel.id == membership_id,
                )
            )
        )

    async def get_evidence_source(
        self, *, actor: AuthenticatedActor, resource_type: str, resource_id: UUID
    ) -> EvidenceSourceSnapshot | None:
        await self._activate_actor(actor)
        if resource_type != "task":
            return None
        row = (
            await self._session.execute(
                select(TaskModel)
                .where(
                    TaskModel.organization_id == actor.organization_id,
                    TaskModel.id == resource_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.assignee_membership_id is None:
            return None
        return EvidenceSourceSnapshot(
            resource_type="task",
            resource_id=resource_id,
            version=row.version,
            completed=row.status == TaskStatus.DONE,
            subject_membership_id=row.assignee_membership_id,
        )

    async def get_skill(
        self,
        *,
        actor: AuthenticatedActor,
        skill_id: UUID,
        for_update: bool = False,
    ) -> Skill | None:
        await self._activate_actor(actor)
        query = select(SkillModel).where(
            SkillModel.organization_id == actor.organization_id,
            SkillModel.id == skill_id,
        )
        if for_update:
            query = query.with_for_update()
        model = await self._session.scalar(query)
        return _skill_to_domain(model) if model is not None else None

    def _add_skill_version(self, *, actor: AuthenticatedActor, skill: Skill) -> None:
        self._session.add(
            SkillVersionModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                skill_id=skill.id,
                version=skill.version,
                name=skill.name,
                normalized_name=skill.normalized_name,
                description=skill.description,
                active=skill.active,
                changed_by_membership_id=actor.membership_id,
                created_at=skill.updated_at,
            )
        )

    async def create_skill(
        self,
        *,
        actor: AuthenticatedActor,
        draft: SkillDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[Skill]:
        await self._activate_actor(actor)
        operation = "people.skill.create"
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_skill_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        now = datetime.now(UTC)
        model = SkillModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            name=draft.name,
            normalized_name=draft.normalized_name,
            description=draft.description,
            active=True,
            version=1,
            created_by_membership_id=actor.membership_id,
            updated_by_membership_id=actor.membership_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        await self._flush_or_conflict()
        skill = _skill_to_domain(model)
        self._session.add(
            SkillVersionModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                skill_id=skill.id,
                version=skill.version,
                name=skill.name,
                normalized_name=skill.normalized_name,
                description=skill.description,
                active=skill.active,
                changed_by_membership_id=actor.membership_id,
                created_at=now,
            )
        )
        after_data: dict[str, object] = {
            "name": skill.name,
            "normalized_name": skill.normalized_name,
            "description": skill.description,
            "active": skill.active,
            "version": skill.version,
        }
        self._audit_success(
            actor=actor,
            action="people.skill.created",
            resource_type="skill",
            resource_id=skill.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data={},
            after_data=after_data,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201
        record.response_body = _skill_to_json(skill)
        return PeopleMutationResult(resource=skill, replayed=False)

    async def _mutate_skill(
        self,
        *,
        actor: AuthenticatedActor,
        skill_id: UUID,
        patch: SkillPatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        operation: str,
        action: str,
    ) -> PeopleMutationResult[Skill]:
        await self._activate_actor(actor)
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_skill_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")
        model = await self._session.scalar(
            select(SkillModel)
            .where(
                SkillModel.organization_id == actor.organization_id,
                SkillModel.id == skill_id,
            )
            .with_for_update()
        )
        if model is None:
            raise PeopleSkillNotFoundError
        current = _skill_to_domain(model)
        if current.version != expected_version:
            raise PeopleSkillVersionMismatchError(current.version)
        now = datetime.now(UTC)
        updated = current.apply(patch, updated_at=now)
        model.name = updated.name
        model.normalized_name = updated.normalized_name
        model.description = updated.description
        model.active = updated.active
        model.version = updated.version
        model.updated_by_membership_id = actor.membership_id
        model.updated_at = now
        self._add_skill_version(actor=actor, skill=updated)
        self._audit_success(
            actor=actor,
            action=action,
            resource_type="skill",
            resource_id=skill_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data={
                "name": current.name,
                "normalized_name": current.normalized_name,
                "description": current.description,
                "active": current.active,
                "version": current.version,
            },
            after_data={
                "name": updated.name,
                "normalized_name": updated.normalized_name,
                "description": updated.description,
                "active": updated.active,
                "version": updated.version,
            },
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = _skill_to_json(updated)
        await self._flush_or_conflict()
        return PeopleMutationResult(resource=updated, replayed=False)

    async def update_skill(
        self,
        *,
        actor: AuthenticatedActor,
        skill_id: UUID,
        patch: SkillPatch,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[Skill]:
        return await self._mutate_skill(
            actor=actor,
            skill_id=skill_id,
            patch=patch,
            expected_version=expected_version,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            operation="people.skill.update",
            action="people.skill.updated",
        )

    async def delete_skill(
        self,
        *,
        actor: AuthenticatedActor,
        skill_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[Skill]:
        return await self._mutate_skill(
            actor=actor,
            skill_id=skill_id,
            patch=SkillPatch.create(active=False, active_supplied=True),
            expected_version=expected_version,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            operation="people.skill.delete",
            action="people.skill.deleted",
        )

    async def list_person_skills(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        include_inactive: bool,
    ) -> tuple[VerifiedPersonSkill, ...]:
        await self._activate_actor(actor)
        query = select(PersonSkillModel).where(
            PersonSkillModel.organization_id == actor.organization_id,
            PersonSkillModel.membership_id == membership_id,
        )
        if not include_inactive:
            query = query.where(PersonSkillModel.active.is_(True))
        models = await self._session.scalars(
            query.order_by(PersonSkillModel.skill_id, PersonSkillModel.id)
        )
        return tuple(_person_skill_to_domain(model) for model in models)

    async def get_person_skill(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        skill_id: UUID,
        include_inactive: bool,
    ) -> VerifiedPersonSkill | None:
        await self._activate_actor(actor)
        query = select(PersonSkillModel).where(
            PersonSkillModel.organization_id == actor.organization_id,
            PersonSkillModel.membership_id == membership_id,
            PersonSkillModel.skill_id == skill_id,
        )
        if not include_inactive:
            query = query.where(PersonSkillModel.active.is_(True))
        model = await self._session.scalar(query)
        return _person_skill_to_domain(model) if model is not None else None

    async def get_person_skill_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.person_skill.upsert",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_person_skill_from_json,
        )

    async def get_person_skill_delete_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.person_skill.delete",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_person_skill_from_json,
        )

    async def upsert_person_skill(
        self,
        *,
        actor: AuthenticatedActor,
        draft: PersonSkillDraft,
        expected_version: int | None,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill]:
        await self._activate_actor(actor)
        operation = "people.person_skill.upsert"
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_person_skill_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        model = await self._session.scalar(
            select(PersonSkillModel)
            .where(
                PersonSkillModel.organization_id == actor.organization_id,
                PersonSkillModel.membership_id == draft.membership_id,
                PersonSkillModel.skill_id == draft.skill_id,
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        before_data: dict[str, object] = {}
        existing_evidence_ids: list[str] = []
        if model is None:
            if expected_version is not None:
                raise PeopleSkillVersionMismatchError(0)
            model = PersonSkillModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                membership_id=draft.membership_id,
                skill_id=draft.skill_id,
                level=draft.level.value,
                verified_by_membership_id=draft.verified_by_membership_id,
                verified_at=now,
                active=True,
                version=1,
                created_at=now,
                updated_at=now,
            )
            action = "people.person_skill.created"
            response_status = 201
            self._session.add(model)
            await self._flush_or_conflict()
        else:
            if expected_version is None or model.version != expected_version:
                raise PeopleSkillVersionMismatchError(model.version)
            existing_evidence_ids = [
                str(evidence_id)
                for evidence_id in await self._session.scalars(
                    select(SkillEvidenceModel.id)
                    .where(
                        SkillEvidenceModel.organization_id == actor.organization_id,
                        SkillEvidenceModel.person_skill_id == model.id,
                    )
                    .order_by(SkillEvidenceModel.created_at, SkillEvidenceModel.id)
                )
            ]
            current = _person_skill_to_domain(model)
            before_data = {
                "skill_id": str(current.skill_id),
                "level": current.level.value,
                "verified_by_membership_id": str(current.verified_by_membership_id),
                "active": current.active,
                "evidence_ids": existing_evidence_ids,
                "version": current.version,
            }
            updated = current.apply(
                PersonSkillPatch.create(
                    level=draft.level.value,
                    verified_by_membership_id=draft.verified_by_membership_id,
                ),
                verified_at=now,
                updated_at=now,
            )
            model.level = updated.level.value
            model.verified_by_membership_id = updated.verified_by_membership_id
            model.verified_at = updated.verified_at
            model.active = True
            model.version = updated.version
            model.updated_at = updated.updated_at
            action = "people.person_skill.updated"
            response_status = 200

        added_evidence_ids: list[str] = []
        for evidence in draft.evidence:
            evidence_id = uuid4()
            added_evidence_ids.append(str(evidence_id))
            self._session.add(
                SkillEvidenceModel(
                    id=evidence_id,
                    organization_id=actor.organization_id,
                    person_skill_id=model.id,
                    evidence_type=evidence.evidence_type,
                    summary=evidence.summary,
                    source_resource_type=evidence.source_resource_type,
                    source_resource_id=evidence.source_resource_id,
                    source_task_id=(
                        evidence.source_resource_id
                        if evidence.source_resource_type == "task"
                        else None
                    ),
                    occurred_at=evidence.occurred_at,
                    created_by_membership_id=actor.membership_id,
                    created_at=now,
                )
            )
        await self._flush_or_conflict()
        person_skill = _person_skill_to_domain(model)
        response_evidence = await self.list_skill_evidence(
            actor=actor, person_skill_id=person_skill.id
        )
        after_data: dict[str, object] = {
            "skill_id": str(person_skill.skill_id),
            "level": person_skill.level.value,
            "verified_by_membership_id": str(person_skill.verified_by_membership_id),
            "active": person_skill.active,
            "evidence_ids": existing_evidence_ids + added_evidence_ids,
            "version": person_skill.version,
        }
        self._audit_success(
            actor=actor,
            action=action,
            resource_type="person_skill",
            resource_id=person_skill.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data=before_data,
            after_data=after_data,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = response_status
        record.response_body = {
            **_person_skill_to_json(person_skill),
            "_evidence": [_skill_evidence_to_json(item) for item in response_evidence],
        }
        return PeopleMutationResult(
            resource=person_skill, replayed=False, evidence=response_evidence
        )

    async def delete_person_skill(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        skill_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill]:
        await self._activate_actor(actor)
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation="people.person_skill.delete",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_person_skill_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")
        model = await self._session.scalar(
            select(PersonSkillModel)
            .where(
                PersonSkillModel.organization_id == actor.organization_id,
                PersonSkillModel.membership_id == membership_id,
                PersonSkillModel.skill_id == skill_id,
                PersonSkillModel.active.is_(True),
            )
            .with_for_update()
        )
        if model is None:
            raise PeopleSkillNotFoundError
        current = _person_skill_to_domain(model)
        if current.version != expected_version:
            raise PeopleSkillVersionMismatchError(current.version)
        before: dict[str, object] = {
            "skill_id": str(current.skill_id),
            "level": current.level.value,
            "verified_by_membership_id": str(current.verified_by_membership_id),
            "active": current.active,
            "version": current.version,
        }
        model.active = False
        model.version += 1
        model.updated_at = datetime.now(UTC)
        deleted = _person_skill_to_domain(model)
        response_evidence = await self.list_skill_evidence(actor=actor, person_skill_id=deleted.id)
        self._audit_success(
            actor=actor,
            action="people.person_skill.deleted",
            resource_type="person_skill",
            resource_id=deleted.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data=before,
            after_data={**before, "active": False, "version": deleted.version},
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = {
            **_person_skill_to_json(deleted),
            "_evidence": [_skill_evidence_to_json(item) for item in response_evidence],
        }
        return PeopleMutationResult(resource=deleted, replayed=False, evidence=response_evidence)

    async def list_skill_evidence(
        self, *, actor: AuthenticatedActor, person_skill_id: UUID
    ) -> tuple[SkillEvidence, ...]:
        await self._activate_actor(actor)
        models = await self._session.scalars(
            select(SkillEvidenceModel)
            .where(
                SkillEvidenceModel.organization_id == actor.organization_id,
                SkillEvidenceModel.person_skill_id == person_skill_id,
            )
            .order_by(SkillEvidenceModel.occurred_at, SkillEvidenceModel.id)
        )
        return tuple(_skill_evidence_to_domain(model) for model in models)

    async def list_work_outcome_evidence(
        self, *, actor: AuthenticatedActor, membership_id: UUID
    ) -> tuple[WorkOutcomeEvidence, ...]:
        await self._activate_actor(actor)
        models = await self._session.scalars(
            select(WorkOutcomeEvidenceModel)
            .where(
                WorkOutcomeEvidenceModel.organization_id == actor.organization_id,
                WorkOutcomeEvidenceModel.membership_id == membership_id,
            )
            .order_by(WorkOutcomeEvidenceModel.observed_at, WorkOutcomeEvidenceModel.id)
        )
        return tuple(_work_evidence_to_domain(model) for model in models)

    async def get_work_outcome_evidence_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[WorkOutcomeEvidence] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.work_outcome_evidence.create",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_work_evidence_from_json,
        )

    async def record_work_outcome_evidence(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        draft: WorkOutcomeEvidenceDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[WorkOutcomeEvidence]:
        await self._activate_actor(actor)
        operation = "people.work_outcome_evidence.create"
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_work_evidence_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        now = datetime.now(UTC)
        model = WorkOutcomeEvidenceModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            membership_id=membership_id,
            evidence_type=draft.evidence_type,
            summary=draft.summary,
            source_resource_type=draft.source_resource_type,
            source_resource_id=draft.source_resource_id,
            source_task_id=(
                draft.source_resource_id if draft.source_resource_type == "task" else None
            ),
            source_resource_version=draft.source_resource_version,
            observed_at=draft.observed_at,
            created_by_membership_id=actor.membership_id,
            created_at=now,
        )
        self._session.add(model)
        await self._flush_or_conflict()
        evidence = _work_evidence_to_domain(model)
        after_data: dict[str, object] = {
            "membership_id": str(evidence.membership_id),
            "evidence_type": evidence.evidence_type.value,
            "source_resource_type": evidence.source_resource_type,
            "source_resource_id": str(evidence.source_resource_id),
            "source_resource_version": evidence.source_resource_version,
        }
        self._audit_success(
            actor=actor,
            action="people.work_outcome_evidence.created",
            resource_type="work_outcome_evidence",
            resource_id=evidence.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data={},
            after_data=after_data,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201
        record.response_body = _work_evidence_to_json(evidence)
        return PeopleMutationResult(resource=evidence, replayed=False)

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
        await self._activate_actor(actor)
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=actor.organization_id,
                actor_membership_id=actor.membership_id,
                action=action,
                outcome=AuditOutcome.REJECTED,
                resource_type="people_capacity",
                resource_id=resource_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data={},
                after_data={},
                reason_data={"code": reason_code},
            )
        )

    async def list_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID | None = None,
        kind: CapacityKind | None = None,
    ) -> tuple[CapacityEntry, ...]:
        await self._activate_actor(actor)
        query = select(CapacityEntryModel).where(
            CapacityEntryModel.organization_id == actor.organization_id
        )
        if membership_id is not None:
            query = query.where(CapacityEntryModel.membership_id == membership_id)
        if kind is not None:
            query = query.where(CapacityEntryModel.kind == kind)
        query = query.order_by(
            CapacityEntryModel.kind, CapacityEntryModel.effective_from, CapacityEntryModel.id
        )
        models = (await self._session.scalars(query)).all()
        return tuple(_capacity_to_domain(m) for m in models)

    async def get_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        capacity_id: UUID,
    ) -> CapacityEntry | None:
        await self._activate_actor(actor)
        model = await self._session.scalar(
            select(CapacityEntryModel).where(
                CapacityEntryModel.organization_id == actor.organization_id,
                CapacityEntryModel.id == capacity_id,
            )
        )
        return _capacity_to_domain(model) if model is not None else None

    async def get_capacity_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.capacity.upsert",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_capacity_from_json,
        )

    async def get_capacity_delete_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.capacity.delete",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_capacity_from_json,
        )

    async def upsert_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        draft: CapacityEntryDraft,
        expected_version: int | None,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry]:
        await self._activate_actor(actor)
        operation = "people.capacity.upsert"
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_capacity_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        if not await self.membership_is_active(
            actor=actor, membership_id=draft.membership_id, for_update=True
        ):
            raise PeopleSkillNotFoundError

        existing_models = (
            await self._session.scalars(
                select(CapacityEntryModel)
                .where(
                    CapacityEntryModel.organization_id == actor.organization_id,
                    CapacityEntryModel.membership_id == draft.membership_id,
                )
                .with_for_update()
            )
        ).all()
        existing_domain = [_capacity_to_domain(m) for m in existing_models]

        matching_model = None
        if draft.kind == CapacityKind.OVERRIDE:
            matching_model = next(
                (
                    m
                    for m in existing_models
                    if m.kind == CapacityKind.OVERRIDE and m.week_start == draft.week_start
                ),
                None,
            )
        else:
            matching_model = next(
                (m for m in existing_models if m.kind == CapacityKind.DEFAULT),
                None,
            )

        now = datetime.now(UTC)
        if matching_model is not None:
            if expected_version is None or matching_model.version != expected_version:
                raise PeopleSkillVersionMismatchError(matching_model.version)

            try:
                ensure_capacity_entry_does_not_overlap(
                    draft,
                    (entry for entry in existing_domain if entry.id != matching_model.id),
                )
            except OverlappingCapacityEntriesError as err:
                raise PeopleSkillConflictError from err

            before_data = _capacity_audit_data(_capacity_to_domain(matching_model))
            matching_model.hours = draft.hours
            matching_model.effective_from = draft.effective_from
            matching_model.effective_to = draft.effective_to
            matching_model.version += 1
            matching_model.updated_at = now
            await self._flush_or_conflict()
            entry = _capacity_to_domain(matching_model)
            self._audit_success(
                actor=actor,
                action="people.capacity.upserted",
                resource_type="capacity_entry",
                resource_id=entry.id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                before_data=before_data,
                after_data=_capacity_audit_data(entry),
            )
            record.state = IdempotencyState.COMPLETED
            record.response_status = 200
            record.response_body = _capacity_to_json(entry)
            return PeopleMutationResult(resource=entry, replayed=False)

        try:
            ensure_capacity_entry_does_not_overlap(draft, existing_domain)
        except OverlappingCapacityEntriesError as err:
            raise PeopleSkillConflictError from err

        model = CapacityEntryModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            membership_id=draft.membership_id,
            kind=draft.kind,
            hours=draft.hours,
            effective_from=draft.effective_from,
            effective_to=draft.effective_to,
            week_start=draft.week_start,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        await self._flush_or_conflict()
        entry = _capacity_to_domain(model)
        self._audit_success(
            actor=actor,
            action="people.capacity.upserted",
            resource_type="capacity_entry",
            resource_id=entry.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data={},
            after_data=_capacity_audit_data(entry),
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201
        record.response_body = _capacity_to_json(entry)
        return PeopleMutationResult(resource=entry, replayed=False)

    async def delete_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        capacity_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry]:
        await self._activate_actor(actor)
        operation = "people.capacity.delete"
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_capacity_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        model = await self._session.scalar(
            select(CapacityEntryModel)
            .where(
                CapacityEntryModel.organization_id == actor.organization_id,
                CapacityEntryModel.id == capacity_id,
            )
            .with_for_update()
        )
        if model is None:
            raise PeopleSkillNotFoundError
        if model.version != expected_version:
            raise PeopleSkillVersionMismatchError(model.version)

        entry = _capacity_to_domain(model)
        await self._session.delete(model)
        await self._flush_or_conflict()
        self._audit_success(
            actor=actor,
            action="people.capacity.deleted",
            resource_type="capacity_entry",
            resource_id=entry.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data=_capacity_audit_data(entry),
            after_data={},
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = _capacity_to_json(entry)
        return PeopleMutationResult(resource=entry, replayed=False)

    async def list_leave(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[LeaveEntry, ...]:
        await self._activate_actor(actor)
        query = select(LeaveEntryModel).where(
            LeaveEntryModel.organization_id == actor.organization_id
        )
        if membership_id is not None:
            query = query.where(LeaveEntryModel.membership_id == membership_id)
        if start_date is not None:
            query = query.where(LeaveEntryModel.end_date >= start_date)
        if end_date is not None:
            query = query.where(LeaveEntryModel.start_date <= end_date)
        query = query.order_by(LeaveEntryModel.start_date, LeaveEntryModel.id)
        models = (await self._session.scalars(query)).all()
        return tuple(_leave_to_domain(m) for m in models)

    async def get_leave(
        self,
        *,
        actor: AuthenticatedActor,
        leave_id: UUID,
    ) -> LeaveEntry | None:
        await self._activate_actor(actor)
        model = await self._session.scalar(
            select(LeaveEntryModel).where(
                LeaveEntryModel.organization_id == actor.organization_id,
                LeaveEntryModel.id == leave_id,
            )
        )
        return _leave_to_domain(model) if model is not None else None

    async def get_leave_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.leave.create",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_leave_from_json,
        )

    async def get_leave_delete_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.leave.delete",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_leave_from_json,
        )

    async def get_leave_update_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry] | None:
        await self._activate_actor(actor)
        return await self._get_idempotency_replay(
            actor=actor,
            operation="people.leave.update",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_leave_from_json,
        )

    async def create_leave(
        self,
        *,
        actor: AuthenticatedActor,
        draft: LeaveEntryDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry]:
        await self._activate_actor(actor)
        operation = "people.leave.create"
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_leave_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        if not await self.membership_is_active(
            actor=actor, membership_id=draft.membership_id, for_update=True
        ):
            raise PeopleSkillNotFoundError

        now = datetime.now(UTC)
        model = LeaveEntryModel(
            id=uuid4(),
            organization_id=actor.organization_id,
            membership_id=draft.membership_id,
            start_date=draft.start_date,
            end_date=draft.end_date,
            unavailable_hours=draft.unavailable_hours,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        await self._flush_or_conflict()
        entry = _leave_to_domain(model)
        self._audit_success(
            actor=actor,
            action="people.leave.created",
            resource_type="leave_entry",
            resource_id=entry.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data={},
            after_data={
                "membership_id": str(entry.membership_id),
                "unavailable_hours": entry.unavailable_hours,
                "start_date": entry.start_date.isoformat(),
                "end_date": entry.end_date.isoformat(),
            },
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 201
        record.response_body = _leave_to_json(entry)
        return PeopleMutationResult(resource=entry, replayed=False)

    async def update_leave(
        self,
        *,
        actor: AuthenticatedActor,
        leave_id: UUID,
        draft: LeaveEntryDraft,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry]:
        await self._activate_actor(actor)
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation="people.leave.update",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_leave_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        model = await self._session.scalar(
            select(LeaveEntryModel)
            .where(
                LeaveEntryModel.organization_id == actor.organization_id,
                LeaveEntryModel.id == leave_id,
            )
            .with_for_update()
        )
        if model is None:
            raise PeopleSkillNotFoundError
        if model.version != expected_version:
            raise PeopleSkillVersionMismatchError(model.version)

        before_data: dict[str, object] = {
            "start_date": model.start_date.isoformat(),
            "end_date": model.end_date.isoformat(),
            "unavailable_hours": model.unavailable_hours,
            "version": model.version,
        }
        model.start_date = draft.start_date
        model.end_date = draft.end_date
        model.unavailable_hours = draft.unavailable_hours
        model.version += 1
        model.updated_at = datetime.now(UTC)
        await self._flush_or_conflict()
        entry = _leave_to_domain(model)
        after_data: dict[str, object] = {
            "start_date": entry.start_date.isoformat(),
            "end_date": entry.end_date.isoformat(),
            "unavailable_hours": entry.unavailable_hours,
            "version": entry.version,
        }
        self._audit_success(
            actor=actor,
            action="people.leave.updated",
            resource_type="leave_entry",
            resource_id=entry.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data=before_data,
            after_data=after_data,
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = _leave_to_json(entry)
        return PeopleMutationResult(resource=entry, replayed=False)

    async def delete_leave(
        self,
        *,
        actor: AuthenticatedActor,
        leave_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry]:
        await self._activate_actor(actor)
        operation = "people.leave.delete"
        record, replay = await self._claim_idempotency(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            loader=_leave_from_json,
        )
        if replay is not None:
            return replay
        if record is None:
            raise RuntimeError("idempotency claim did not return a record")

        model = await self._session.scalar(
            select(LeaveEntryModel)
            .where(
                LeaveEntryModel.organization_id == actor.organization_id,
                LeaveEntryModel.id == leave_id,
            )
            .with_for_update()
        )
        if model is None:
            raise PeopleSkillNotFoundError
        if model.version != expected_version:
            raise PeopleSkillVersionMismatchError(model.version)

        entry = _leave_to_domain(model)
        await self._session.delete(model)
        await self._flush_or_conflict()
        self._audit_success(
            actor=actor,
            action="people.leave.deleted",
            resource_type="leave_entry",
            resource_id=entry.id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            before_data={"unavailable_hours": entry.unavailable_hours, "version": entry.version},
            after_data={},
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status = 200
        record.response_body = _leave_to_json(entry)
        return PeopleMutationResult(resource=entry, replayed=False)

    async def load_workload_inputs(
        self,
        *,
        actor: AuthenticatedActor,
        week_start: date,
        membership_id: UUID | None,
    ) -> tuple[WorkloadInput, ...]:
        await self._activate_actor(actor)

        # 1. Query project weeks starting on week_start
        project_weeks = (
            await self._session.scalars(
                select(ProjectWeekModel)
                .where(
                    ProjectWeekModel.organization_id == actor.organization_id,
                    ProjectWeekModel.start_date == week_start,
                )
                .order_by(ProjectWeekModel.project_id, ProjectWeekModel.week_number)
            )
        ).all()
        if not project_weeks:
            return ()

        # 2. Resolve target memberships
        if membership_id is not None:
            active = await self.membership_is_active(actor=actor, membership_id=membership_id)
            if not active:
                raise PeopleSkillNotFoundError
            target_ids = [membership_id]
        else:
            memberships = (
                await self._session.scalars(
                    select(MembershipModel)
                    .where(
                        MembershipModel.organization_id == actor.organization_id,
                        MembershipModel.is_active.is_(True),
                    )
                    .order_by(MembershipModel.created_at)
                )
            ).all()
            target_ids = [m.id for m in memberships]

        if not target_ids:
            return ()

        # 3. Load capacity entries
        capacity_models = (
            await self._session.scalars(
                select(CapacityEntryModel).where(
                    CapacityEntryModel.organization_id == actor.organization_id,
                    CapacityEntryModel.membership_id.in_(target_ids),
                )
            )
        ).all()

        # 4. Load leave entries overlapping any project week
        min_start = min(pw.start_date for pw in project_weeks)
        max_end = max(pw.end_date for pw in project_weeks)
        leave_models = (
            await self._session.scalars(
                select(LeaveEntryModel).where(
                    LeaveEntryModel.organization_id == actor.organization_id,
                    LeaveEntryModel.membership_id.in_(target_ids),
                    LeaveEntryModel.start_date <= max_end,
                    LeaveEntryModel.end_date >= min_start,
                )
            )
        ).all()

        # 5. Load open tasks
        pw_ids = [pw.id for pw in project_weeks]
        task_models = (
            await self._session.scalars(
                select(TaskModel).where(
                    TaskModel.organization_id == actor.organization_id,
                    TaskModel.assignee_membership_id.in_(target_ids),
                    TaskModel.project_week_id.in_(pw_ids),
                    TaskModel.status.in_([TaskStatus.TO_DO, TaskStatus.IN_PROGRESS]),
                )
            )
        ).all()

        # 6. Build WorkloadInput
        inputs: list[WorkloadInput] = []
        for pw in project_weeks:
            for mid in target_ids:
                default_entry = next(
                    (
                        c
                        for c in capacity_models
                        if c.membership_id == mid
                        and c.kind == CapacityKind.DEFAULT
                        and c.effective_from <= pw.end_date
                        and c.effective_to >= pw.start_date
                    ),
                    None,
                )
                default_hours = default_entry.hours if default_entry is not None else 0

                override_entry = next(
                    (
                        c
                        for c in capacity_models
                        if c.membership_id == mid
                        and c.kind == CapacityKind.OVERRIDE
                        and c.week_start == pw.start_date
                    ),
                    None,
                )
                override_hours = override_entry.hours if override_entry is not None else None

                member_leaves = [
                    leave
                    for leave in leave_models
                    if leave.membership_id == mid
                    and leave.start_date <= pw.end_date
                    and leave.end_date >= pw.start_date
                ]
                leave_hours = min(
                    sum(
                        _leave_hours_in_range(leave, pw.start_date, pw.end_date)
                        for leave in member_leaves
                    ),
                    168,
                )

                member_tasks = [t for t in task_models if t.assignee_membership_id == mid]
                efforts = tuple(
                    t.estimated_effort_hours
                    for t in member_tasks
                    if t.estimated_effort_hours is not None
                    and 1 <= t.estimated_effort_hours <= 10_000
                )

                inputs.append(
                    WorkloadInput(
                        membership_id=mid,
                        project_week_id=pw.id,
                        default_capacity_hours=default_hours,
                        override_capacity_hours=override_hours,
                        leave_hours=leave_hours,
                        open_task_effort_hours=efforts,
                    )
                )

        return tuple(inputs)


class SqlAlchemyPeopleCapacityTransactionFactory:
    """Create one commit-or-rollback session for each People Skills operation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[PeopleCapacityRepository]:
        async with self._session_factory.begin() as session:
            yield SqlAlchemyPeopleCapacityRepository(session)
