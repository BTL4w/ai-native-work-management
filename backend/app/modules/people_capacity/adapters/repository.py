"""SQLAlchemy People Skills persistence with RLS, idempotency, and safe audit."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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
from app.modules.work.adapters.database_models import (
    IdempotencyRecordModel,
    IdempotencyState,
    TaskModel,
)
from app.modules.work.domain.tasks import TaskStatus

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
                    text(
                        "SELECT public.lock_active_membership("
                        ":organization_id, :membership_id)"
                    ),
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


class SqlAlchemyPeopleCapacityTransactionFactory:
    """Create one commit-or-rollback session for each People Skills operation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[PeopleCapacityRepository]:
        async with self._session_factory.begin() as session:
            yield SqlAlchemyPeopleCapacityRepository(session)
