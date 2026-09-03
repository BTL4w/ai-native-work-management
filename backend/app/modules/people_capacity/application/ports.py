"""Typed People Skills persistence ports owned by the application boundary."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.people_capacity.domain.availability import (
    CapacityEntry,
    CapacityEntryDraft,
    CapacityKind,
    LeaveEntry,
    LeaveEntryDraft,
)
from app.modules.people_capacity.domain.skills import (
    PersonSkillDraft,
    Skill,
    SkillDraft,
    SkillEvidence,
    SkillPatch,
    VerifiedPersonSkill,
    WorkOutcomeEvidence,
    WorkOutcomeEvidenceDraft,
)
from app.modules.people_capacity.domain.workload import WorkloadInput


@dataclass(frozen=True, slots=True)
class PeopleMutationResult[T]:
    """A persisted resource and whether it came from idempotent replay."""

    resource: T
    replayed: bool
    evidence: tuple[SkillEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceSourceSnapshot:
    """Minimal verified source facts exposed to application policy."""

    resource_type: str
    resource_id: UUID
    version: int
    completed: bool
    subject_membership_id: UUID


class PeopleCapacityRepository(Protocol):
    async def list_skills(self, *, actor: AuthenticatedActor) -> tuple[Skill, ...]: ...

    async def membership_is_active(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        for_update: bool = False,
    ) -> bool: ...

    async def get_evidence_source(
        self, *, actor: AuthenticatedActor, resource_type: str, resource_id: UUID
    ) -> EvidenceSourceSnapshot | None: ...

    async def create_skill(
        self,
        *,
        actor: AuthenticatedActor,
        draft: SkillDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[Skill]: ...

    async def get_skill(
        self, *, actor: AuthenticatedActor, skill_id: UUID, for_update: bool = False
    ) -> Skill | None: ...

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
    ) -> PeopleMutationResult[Skill]: ...

    async def delete_skill(
        self,
        *,
        actor: AuthenticatedActor,
        skill_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[Skill]: ...

    async def list_person_skills(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        include_inactive: bool,
    ) -> tuple[VerifiedPersonSkill, ...]: ...

    async def get_person_skill(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        skill_id: UUID,
        include_inactive: bool,
    ) -> VerifiedPersonSkill | None: ...

    async def get_person_skill_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill] | None: ...

    async def get_person_skill_delete_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill] | None: ...

    async def upsert_person_skill(
        self,
        *,
        actor: AuthenticatedActor,
        draft: PersonSkillDraft,
        expected_version: int | None,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[VerifiedPersonSkill]: ...

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
    ) -> PeopleMutationResult[VerifiedPersonSkill]: ...

    async def list_skill_evidence(
        self, *, actor: AuthenticatedActor, person_skill_id: UUID
    ) -> tuple[SkillEvidence, ...]: ...

    async def list_work_outcome_evidence(
        self, *, actor: AuthenticatedActor, membership_id: UUID
    ) -> tuple[WorkOutcomeEvidence, ...]: ...

    async def get_work_outcome_evidence_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[WorkOutcomeEvidence] | None: ...

    async def record_work_outcome_evidence(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID,
        draft: WorkOutcomeEvidenceDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[WorkOutcomeEvidence]: ...

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

    async def list_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID | None = None,
        kind: CapacityKind | None = None,
    ) -> tuple[CapacityEntry, ...]: ...

    async def get_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        capacity_id: UUID,
    ) -> CapacityEntry | None: ...

    async def get_capacity_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry] | None: ...

    async def get_capacity_delete_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry] | None: ...

    async def upsert_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        draft: CapacityEntryDraft,
        expected_version: int | None,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry]: ...

    async def delete_capacity(
        self,
        *,
        actor: AuthenticatedActor,
        capacity_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[CapacityEntry]: ...

    async def list_leave(
        self,
        *,
        actor: AuthenticatedActor,
        membership_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[LeaveEntry, ...]: ...

    async def get_leave(
        self,
        *,
        actor: AuthenticatedActor,
        leave_id: UUID,
    ) -> LeaveEntry | None: ...

    async def get_leave_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry] | None: ...

    async def get_leave_delete_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry] | None: ...

    async def get_leave_update_replay(
        self,
        *,
        actor: AuthenticatedActor,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry] | None: ...

    async def create_leave(
        self,
        *,
        actor: AuthenticatedActor,
        draft: LeaveEntryDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry]: ...

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
    ) -> PeopleMutationResult[LeaveEntry]: ...

    async def delete_leave(
        self,
        *,
        actor: AuthenticatedActor,
        leave_id: UUID,
        expected_version: int,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[LeaveEntry]: ...

    async def load_workload_inputs(
        self,
        *,
        actor: AuthenticatedActor,
        week_start: date,
        membership_id: UUID | None,
    ) -> tuple[WorkloadInput, ...]: ...


PeopleCapacityTransactionFactory = Callable[
    [], AbstractAsyncContextManager[PeopleCapacityRepository]
]
