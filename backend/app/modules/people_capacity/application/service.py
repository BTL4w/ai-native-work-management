"""Authorization, provenance, fingerprints, and transactions for People Skills."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.application.ports import (
    PeopleCapacityRepository,
    PeopleCapacityTransactionFactory,
    PeopleMutationResult,
)
from app.modules.people_capacity.domain.skills import (
    PeopleSkillError,
    PeopleSkillForbiddenError,
    PeopleSkillNotFoundError,
    PeopleSkillReferenceError,
    PersonSkillDraft,
    Skill,
    SkillDraft,
    SkillEvidence,
    SkillEvidenceDraft,
    SkillEvidenceType,
    SkillPatch,
    VerifiedPersonSkill,
    WorkOutcomeEvidence,
    WorkOutcomeEvidenceDraft,
)

_WRITERS = frozenset({MembershipRole.ADMIN, MembershipRole.MANAGER})


def _fingerprint(operation: str, values: dict[str, object]) -> str:
    canonical = json.dumps(
        {"operation": operation, "values": values},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class PeopleCapacityService:
    def __init__(self, transaction_factory: PeopleCapacityTransactionFactory) -> None:
        self._transactions = transaction_factory

    async def list_skills(self, *, actor: AuthenticatedActor) -> tuple[Skill, ...]:
        async with self._transactions() as repository:
            return await repository.list_skills(actor=actor)

    async def get_skill(self, *, actor: AuthenticatedActor, skill_id: UUID) -> Skill:
        async with self._transactions() as repository:
            skill = await repository.get_skill(actor=actor, skill_id=skill_id)
        if skill is None:
            raise PeopleSkillNotFoundError
        return skill

    async def list_person_skills(
        self, *, actor: AuthenticatedActor, membership_id: UUID
    ) -> tuple[VerifiedPersonSkill, ...]:
        async with self._transactions() as repository:
            if not await repository.membership_is_active(actor=actor, membership_id=membership_id):
                raise PeopleSkillNotFoundError
            return await repository.list_person_skills(
                actor=actor,
                membership_id=membership_id,
                include_inactive=actor.role in _WRITERS,
            )

    async def get_person_skill(
        self, *, actor: AuthenticatedActor, membership_id: UUID, skill_id: UUID
    ) -> VerifiedPersonSkill:
        async with self._transactions() as repository:
            if not await repository.membership_is_active(actor=actor, membership_id=membership_id):
                raise PeopleSkillNotFoundError
            value = await repository.get_person_skill(
                actor=actor,
                membership_id=membership_id,
                skill_id=skill_id,
                include_inactive=actor.role in _WRITERS,
            )
        if value is None:
            raise PeopleSkillNotFoundError
        return value

    async def list_skill_evidence(
        self, *, actor: AuthenticatedActor, person_skill_id: UUID
    ) -> tuple[SkillEvidence, ...]:
        async with self._transactions() as repository:
            return await repository.list_skill_evidence(
                actor=actor, person_skill_id=person_skill_id
            )

    async def list_work_outcome_evidence(
        self, *, actor: AuthenticatedActor, membership_id: UUID
    ) -> tuple[WorkOutcomeEvidence, ...]:
        async with self._transactions() as repository:
            if not await repository.membership_is_active(actor=actor, membership_id=membership_id):
                raise PeopleSkillNotFoundError
            return await repository.list_work_outcome_evidence(
                actor=actor, membership_id=membership_id
            )

    async def _reject(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        reason_code: str,
        resource_id: UUID | None = None,
    ) -> None:
        async with self._transactions() as repository:
            await repository.audit_rejection(
                actor=actor,
                action=action,
                request_id=request_id,
                reason_code=reason_code,
                idempotency_key=idempotency_key,
                resource_id=resource_id,
            )

    async def _require_writer(
        self,
        *,
        repository: PeopleCapacityRepository,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str,
        resource_id: UUID | None = None,
    ) -> None:
        if actor.role in _WRITERS:
            return
        await self._reject(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason_code="FORBIDDEN",
            resource_id=resource_id,
        )
        raise PeopleSkillForbiddenError

    async def authorize_mutation(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
    ) -> None:
        """Reject and audit non-writers before HTTP payload validation completes."""
        if actor.role in _WRITERS:
            return
        await self._reject(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason_code="FORBIDDEN",
        )
        raise PeopleSkillForbiddenError

    async def audit_transport_rejection(
        self,
        *,
        actor: AuthenticatedActor,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        reason_code: str,
    ) -> None:
        """Persist a safe rejection raised before the application use case starts."""
        await self._reject(
            actor=actor,
            action=action,
            request_id=request_id,
            idempotency_key=idempotency_key,
            reason_code=reason_code,
        )

    async def _require_active_member(
        self,
        *,
        repository: PeopleCapacityRepository,
        actor: AuthenticatedActor,
        membership_id: UUID,
        for_update: bool = False,
    ) -> None:
        if not await repository.membership_is_active(
            actor=actor,
            membership_id=membership_id,
            for_update=for_update,
        ):
            raise PeopleSkillReferenceError("membership_id")

    async def _require_evidence_source(
        self,
        *,
        repository: PeopleCapacityRepository,
        actor: AuthenticatedActor,
        evidence_type: SkillEvidenceType,
        resource_type: str,
        resource_id: UUID,
        expected_version: int | None,
        membership_id: UUID,
    ) -> None:
        if evidence_type not in {
            SkillEvidenceType.COMPLETED_TASK,
            SkillEvidenceType.REVIEW_OUTCOME,
        }:
            return
        expected_resource_type = {
            SkillEvidenceType.COMPLETED_TASK: "task",
            SkillEvidenceType.REVIEW_OUTCOME: "review",
        }[evidence_type]
        if resource_type != expected_resource_type:
            raise PeopleSkillReferenceError("source_resource_type")
        source = await repository.get_evidence_source(
            actor=actor, resource_type=resource_type, resource_id=resource_id
        )
        if (
            source is None
            or not source.completed
            or source.subject_membership_id != membership_id
            or (expected_version is not None and source.version != expected_version)
        ):
            raise PeopleSkillReferenceError("source_resource_id")

    async def create_skill(
        self,
        *,
        actor: AuthenticatedActor,
        name: str,
        description: str | None,
        request_id: str,
        idempotency_key: str,
    ) -> PeopleMutationResult[Skill]:
        async with self._transactions() as repository:
            await self._require_writer(
                repository=repository,
                actor=actor,
                action="people.skill.created",
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
            try:
                draft = SkillDraft.create(name=name, description=description)
                return await repository.create_skill(
                    actor=actor,
                    draft=draft,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_fingerprint(
                        "people.skill.create",
                        {"name": draft.name, "description": draft.description},
                    ),
                )
            except PeopleSkillError as error:
                await self._reject(
                    actor=actor,
                    action="people.skill.created",
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    reason_code=type(error).__name__,
                )
                raise

    async def update_skill(
        self,
        *,
        actor: AuthenticatedActor,
        skill_id: UUID,
        name: str | None,
        name_supplied: bool,
        description: str | None,
        description_supplied: bool,
        active: bool | None,
        active_supplied: bool,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PeopleMutationResult[Skill]:
        action = "people.skill.updated"
        async with self._transactions() as repository:
            await self._require_writer(
                repository=repository,
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=skill_id,
            )
            try:
                patch = SkillPatch.create(
                    name=name,
                    name_supplied=name_supplied,
                    description=description,
                    description_supplied=description_supplied,
                    active=active,
                    active_supplied=active_supplied,
                )
                patch.validate_not_empty()
                return await repository.update_skill(
                    actor=actor,
                    skill_id=skill_id,
                    patch=patch,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_fingerprint(
                        "people.skill.update",
                        {
                            "skill_id": skill_id,
                            "name": patch.name if patch.name_supplied else "__omitted__",
                            "description": (
                                patch.description if patch.description_supplied else "__omitted__"
                            ),
                            "active": patch.active if patch.active_supplied else "__omitted__",
                            "expected_version": expected_version,
                        },
                    ),
                )
            except PeopleSkillError as error:
                await self._reject(
                    actor=actor,
                    action=action,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    reason_code=type(error).__name__,
                    resource_id=skill_id,
                )
                raise

    async def delete_skill(
        self,
        *,
        actor: AuthenticatedActor,
        skill_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PeopleMutationResult[Skill]:
        action = "people.skill.deleted"
        async with self._transactions() as repository:
            await self._require_writer(
                repository=repository,
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=skill_id,
            )
            try:
                return await repository.delete_skill(
                    actor=actor,
                    skill_id=skill_id,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_fingerprint(
                        "people.skill.delete",
                        {"skill_id": skill_id, "expected_version": expected_version},
                    ),
                )
            except PeopleSkillError as error:
                await self._reject(
                    actor=actor,
                    action=action,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    reason_code=type(error).__name__,
                    resource_id=skill_id,
                )
                raise

    async def set_person_skill(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        skill_id: UUID,
        level: int,
        evidence: tuple[SkillEvidenceDraft, ...],
        expected_version: int | None,
        request_id: str,
        idempotency_key: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill]:
        action = "people.person_skill.upserted"
        async with self._transactions() as repository:
            await self._require_writer(
                repository=repository,
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=skill_id,
            )
            try:
                if any(item.evidence_type is SkillEvidenceType.CERTIFICATE for item in evidence):
                    raise PeopleSkillReferenceError("evidence_type")
                evidence = tuple(
                    replace(
                        item,
                        source_resource_type="manager_note",
                        source_resource_id=actor.membership_id,
                    )
                    if item.evidence_type is SkillEvidenceType.MANAGER_NOTE
                    else item
                    for item in evidence
                )
                draft = PersonSkillDraft.create(
                    membership_id=membership_id,
                    skill_id=skill_id,
                    level=level,
                    verified_by_membership_id=actor.membership_id,
                    evidence=evidence,
                )
                request_fingerprint = _fingerprint(
                    "people.person_skill.upsert",
                    {
                        "membership_id": membership_id,
                        "skill_id": skill_id,
                        "level": draft.level.value,
                        "evidence": [
                            {
                                "evidence_type": item.evidence_type.value,
                                "summary": item.summary,
                                "source_resource_type": item.source_resource_type,
                                "source_resource_id": item.source_resource_id,
                                "occurred_at": item.occurred_at,
                            }
                            for item in draft.evidence
                        ],
                        "expected_version": expected_version,
                    },
                )
                replay = await repository.get_person_skill_replay(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if replay is not None:
                    return replay
                await self._require_active_member(
                    repository=repository,
                    actor=actor,
                    membership_id=membership_id,
                    for_update=True,
                )
                skill = await repository.get_skill(
                    actor=actor, skill_id=skill_id, for_update=True
                )
                if skill is None or not skill.active:
                    raise PeopleSkillReferenceError("skill_id")
                for item in sorted(
                    evidence,
                    key=lambda value: (
                        value.source_resource_type,
                        str(value.source_resource_id),
                    ),
                ):
                    await self._require_evidence_source(
                        repository=repository,
                        actor=actor,
                        evidence_type=item.evidence_type,
                        resource_type=item.source_resource_type,
                        resource_id=item.source_resource_id,
                        expected_version=None,
                        membership_id=membership_id,
                    )
                return await repository.upsert_person_skill(
                    actor=actor,
                    draft=draft,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
            except PeopleSkillError as error:
                await self._reject(
                    actor=actor,
                    action=action,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    reason_code=type(error).__name__,
                    resource_id=skill_id,
                )
                raise

    async def record_work_outcome_evidence(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        evidence: WorkOutcomeEvidenceDraft,
        request_id: str,
        idempotency_key: str,
    ) -> PeopleMutationResult[WorkOutcomeEvidence]:
        action = "people.work_outcome_evidence.created"
        async with self._transactions() as repository:
            await self._require_writer(
                repository=repository,
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=evidence.source_resource_id,
            )
            try:
                request_fingerprint = _fingerprint(
                    "people.work_evidence.create",
                    {
                        "membership_id": membership_id,
                        "evidence_type": evidence.evidence_type.value,
                        "summary": evidence.summary,
                        "source_resource_type": evidence.source_resource_type,
                        "source_resource_id": evidence.source_resource_id,
                        "source_resource_version": evidence.source_resource_version,
                        "observed_at": evidence.observed_at,
                    },
                )
                replay = await repository.get_work_outcome_evidence_replay(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if replay is not None:
                    return replay
                await self._require_active_member(
                    repository=repository,
                    actor=actor,
                    membership_id=membership_id,
                    for_update=True,
                )
                await self._require_evidence_source(
                    repository=repository,
                    actor=actor,
                    evidence_type=evidence.evidence_type,
                    resource_type=evidence.source_resource_type,
                    resource_id=evidence.source_resource_id,
                    expected_version=evidence.source_resource_version,
                    membership_id=membership_id,
                )
                return await repository.record_work_outcome_evidence(
                    actor=actor,
                    membership_id=membership_id,
                    draft=evidence,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
            except PeopleSkillError as error:
                await self._reject(
                    actor=actor,
                    action=action,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    reason_code=type(error).__name__,
                    resource_id=evidence.source_resource_id,
                )
                raise

    async def delete_person_skill(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        skill_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill]:
        action = "people.person_skill.deleted"
        async with self._transactions() as repository:
            await self._require_writer(
                repository=repository,
                actor=actor,
                action=action,
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_id=skill_id,
            )
            try:
                request_fingerprint = _fingerprint(
                    "people.person_skill.delete",
                    {
                        "membership_id": membership_id,
                        "skill_id": skill_id,
                        "expected_version": expected_version,
                    },
                )
                replay = await repository.get_person_skill_delete_replay(
                    actor=actor,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if replay is not None:
                    return replay
                await self._require_active_member(
                    repository=repository,
                    actor=actor,
                    membership_id=membership_id,
                    for_update=True,
                )
                return await repository.delete_person_skill(
                    actor=actor,
                    membership_id=membership_id,
                    skill_id=skill_id,
                    expected_version=expected_version,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
            except PeopleSkillError as error:
                await self._reject(
                    actor=actor,
                    action=action,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    reason_code=type(error).__name__,
                    resource_id=skill_id,
                )
                raise
