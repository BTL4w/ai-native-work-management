"""Typed People Skills persistence ports owned by the application boundary."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.people_capacity.domain.skills import (
    PersonSkillDraft,
    Skill,
    SkillDraft,
    VerifiedPersonSkill,
    WorkOutcomeEvidence,
    WorkOutcomeEvidenceDraft,
)


@dataclass(frozen=True, slots=True)
class PeopleMutationResult[T]:
    """A persisted resource and whether it came from idempotent replay."""

    resource: T
    replayed: bool


class PeopleCapacityRepository(Protocol):
    async def list_skills(self, *, actor: AuthenticatedActor) -> tuple[Skill, ...]: ...

    async def create_skill(
        self,
        *,
        actor: AuthenticatedActor,
        draft: SkillDraft,
        request_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> PeopleMutationResult[Skill]: ...

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


PeopleCapacityTransactionFactory = Callable[
    [], AbstractAsyncContextManager[PeopleCapacityRepository]
]
