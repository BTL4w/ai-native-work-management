"""Authorization and provenance tests for the People Capacity application service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.application.ports import (
    EvidenceSourceSnapshot,
    PeopleMutationResult,
)
from app.modules.people_capacity.application.service import PeopleCapacityService
from app.modules.people_capacity.domain.skills import (
    InvalidEvidenceFieldError,
    PeopleSkillForbiddenError,
    PeopleSkillReferenceError,
    Skill,
    SkillEvidenceDraft,
    SkillPatch,
    WorkOutcomeEvidenceDraft,
)


def _actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="person@example.test",
        display_name="Person",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


class FakeRepository:
    def __init__(self, actor: AuthenticatedActor) -> None:
        self.actor = actor
        self.active_memberships = {actor.membership_id}
        self.sources: dict[tuple[str, UUID], EvidenceSourceSnapshot] = {}
        self.person_skill_replay: PeopleMutationResult[Any] | None = None
        self.work_evidence_replay: PeopleMutationResult[Any] | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []
        now = datetime(2026, 8, 26, tzinfo=UTC)
        self.skill = Skill(
            id=uuid4(),
            organization_id=actor.organization_id,
            name="Delivery Planning",
            normalized_name="delivery planning",
            description=None,
            active=True,
            version=1,
            created_at=now,
            updated_at=now,
        )

    async def membership_is_active(self, **values: Any) -> bool:
        self.calls.append(("membership_is_active", values))
        return values["membership_id"] in self.active_memberships

    async def get_evidence_source(self, **values: Any) -> EvidenceSourceSnapshot | None:
        self.calls.append(("get_evidence_source", values))
        return self.sources.get((values["resource_type"], values["resource_id"]))

    async def create_skill(self, **values: Any) -> PeopleMutationResult[Skill]:
        self.calls.append(("create_skill", values))
        return PeopleMutationResult(resource=self.skill, replayed=False)

    async def list_skills(self, **values: Any) -> tuple[Skill, ...]:
        self.calls.append(("list_skills", values))
        return (self.skill,)

    async def get_skill(self, **values: Any) -> Skill | None:
        self.calls.append(("get_skill", values))
        return self.skill if values["skill_id"] == self.skill.id else None

    async def update_skill(self, **values: Any) -> PeopleMutationResult[Skill]:
        self.calls.append(("update_skill", values))
        return PeopleMutationResult(resource=self.skill, replayed=False)

    async def list_person_skills(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("list_person_skills", values))
        return ()

    async def get_person_skill(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("get_person_skill", values))
        return None

    async def get_person_skill_replay(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("get_person_skill_replay", values))
        return self.person_skill_replay

    async def get_person_skill_delete_replay(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("get_person_skill_delete_replay", values))
        return None

    async def delete_person_skill(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("delete_person_skill", values))
        return PeopleMutationResult(resource=object(), replayed=False)

    async def list_work_outcome_evidence(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("list_work_outcome_evidence", values))
        return ()

    async def get_work_outcome_evidence_replay(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("get_work_outcome_evidence_replay", values))
        return self.work_evidence_replay

    async def upsert_person_skill(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("upsert_person_skill", values))
        return PeopleMutationResult(resource=object(), replayed=False)

    async def record_work_outcome_evidence(self, **values: Any):  # type: ignore[no-untyped-def]
        self.calls.append(("record_work_outcome_evidence", values))
        return PeopleMutationResult(resource=object(), replayed=False)

    async def audit_rejection(self, **values: Any) -> None:
        self.calls.append(("audit_rejection", values))


def _service(repository: FakeRepository) -> PeopleCapacityService:
    @asynccontextmanager
    async def transactions():
        start = len(repository.calls)
        try:
            yield repository
        except Exception:
            repository.calls[start:] = [
                call for call in repository.calls[start:] if call[0] == "audit_rejection"
            ]
            raise

    return PeopleCapacityService(transactions)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_manager_create_skill_normalizes_input_before_fingerprinting() -> None:
    actor = _actor()
    repository = FakeRepository(actor)

    result = await _service(repository).create_skill(
        actor=actor,
        name="  Delivery Planning  ",
        description="  Plan delivery work  ",
        request_id="skill-request-1",
        idempotency_key="skill-create-key-1",
    )

    assert result.resource == repository.skill
    call = next(values for name, values in repository.calls if name == "create_skill")
    assert call["draft"].name == "Delivery Planning"
    assert call["draft"].description == "Plan delivery work"
    assert call["request_fingerprint"] == (
        "18b0ca0df83f50d3d6dc7faf891038306ac4b08baf59911d5ecd673310066f99"
    )


@pytest.mark.asyncio
async def test_employee_reads_skills_but_mutation_is_rejected_and_audited() -> None:
    actor = _actor(MembershipRole.EMPLOYEE)
    repository = FakeRepository(actor)
    service = _service(repository)

    assert await service.list_skills(actor=actor) == (repository.skill,)
    with pytest.raises(PeopleSkillForbiddenError):
        await service.create_skill(
            actor=actor,
            name="Facilitation",
            description=None,
            request_id="employee-write-1",
            idempotency_key="employee-write-key",
        )

    rejection = next(values for name, values in repository.calls if name == "audit_rejection")
    assert rejection["action"] == "people.skill.created"
    assert rejection["reason_code"] == "FORBIDDEN"
    assert not any(name == "create_skill" for name, _ in repository.calls)


@pytest.mark.asyncio
async def test_set_person_skill_rejects_inactive_or_cross_tenant_member_with_audit() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    missing_member = uuid4()

    with pytest.raises(PeopleSkillReferenceError):
        await _service(repository).set_person_skill(
            actor=actor,
            membership_id=missing_member,
            skill_id=repository.skill.id,
            level=3,
            evidence=(),
            expected_version=None,
            request_id="person-skill-1",
            idempotency_key="person-skill-key1",
        )

    assert not any(name == "upsert_person_skill" for name, _ in repository.calls)
    rejection = next(values for name, values in repository.calls if name == "audit_rejection")
    assert rejection["reason_code"] == "PeopleSkillReferenceError"


@pytest.mark.asyncio
async def test_work_outcome_requires_completed_task_at_exact_version() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    employee_id, task_id = uuid4(), uuid4()
    repository.active_memberships.add(employee_id)
    repository.sources[("task", task_id)] = EvidenceSourceSnapshot(
        resource_type="task",
        resource_id=task_id,
        version=4,
        completed=True,
        subject_membership_id=employee_id,
    )
    service = _service(repository)

    with pytest.raises(PeopleSkillReferenceError):
        await service.record_work_outcome_evidence(
            actor=actor,
            membership_id=employee_id,
            evidence=WorkOutcomeEvidenceDraft.create(
                evidence_type="COMPLETED_TASK",
                summary="Delivered the launch",
                source_resource_type="task",
                source_resource_id=task_id,
                source_resource_version=3,
                observed_at=datetime(2026, 8, 26, tzinfo=UTC),
            ),
            request_id="work-evidence-1",
            idempotency_key="work-evidence-key1",
        )

    assert not any(name == "record_work_outcome_evidence" for name, _ in repository.calls)


@pytest.mark.asyncio
async def test_person_skill_completed_task_evidence_must_have_valid_provenance() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    employee_id, task_id = uuid4(), uuid4()
    repository.active_memberships.add(employee_id)
    evidence = SkillEvidenceDraft.create(
        evidence_type="COMPLETED_TASK",
        summary="Delivered the launch",
        source_resource_type="task",
        source_resource_id=task_id,
        occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
    )

    with pytest.raises(PeopleSkillReferenceError):
        await _service(repository).set_person_skill(
            actor=actor,
            membership_id=employee_id,
            skill_id=repository.skill.id,
            level=4,
            evidence=(evidence,),
            expected_version=None,
            request_id="person-skill-2",
            idempotency_key="person-skill-key2",
        )


@pytest.mark.asyncio
async def test_manager_updates_skill_with_exact_version_and_normalized_patch() -> None:
    actor = _actor()
    repository = FakeRepository(actor)

    await _service(repository).update_skill(
        actor=actor,
        skill_id=repository.skill.id,
        name="  Facilitation  ",
        name_supplied=True,
        description=None,
        description_supplied=True,
        active=None,
        active_supplied=False,
        expected_version=1,
        request_id="skill-update-1",
        idempotency_key="skill-update-key1",
    )

    call = next(values for name, values in repository.calls if name == "update_skill")
    assert call["patch"] == SkillPatch.create(
        name="Facilitation",
        name_supplied=True,
        description=None,
        description_supplied=True,
    )
    assert call["expected_version"] == 1


@pytest.mark.asyncio
async def test_employee_can_read_member_skills_and_work_evidence() -> None:
    actor = _actor(MembershipRole.EMPLOYEE)
    repository = FakeRepository(actor)
    repository.active_memberships.add(uuid4())
    member_id = next(
        value for value in repository.active_memberships if value != actor.membership_id
    )
    service = _service(repository)

    assert await service.list_person_skills(actor=actor, membership_id=member_id) == ()
    assert await service.list_work_outcome_evidence(actor=actor, membership_id=member_id) == ()


@pytest.mark.asyncio
async def test_valid_completed_task_evidence_is_persisted() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    employee_id, task_id = uuid4(), uuid4()
    repository.active_memberships.add(employee_id)
    repository.sources[("task", task_id)] = EvidenceSourceSnapshot(
        resource_type="task",
        resource_id=task_id,
        version=4,
        completed=True,
        subject_membership_id=employee_id,
    )

    await _service(repository).record_work_outcome_evidence(
        actor=actor,
        membership_id=employee_id,
        evidence=WorkOutcomeEvidenceDraft.create(
            evidence_type="COMPLETED_TASK",
            summary="Delivered the launch",
            source_resource_type="task",
            source_resource_id=task_id,
            source_resource_version=4,
            observed_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        request_id="work-evidence-2",
        idempotency_key="work-evidence-key2",
    )

    assert any(name == "record_work_outcome_evidence" for name, _ in repository.calls)


@pytest.mark.asyncio
async def test_completed_task_evidence_must_belong_to_target_member() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    target_member, other_member, task_id = uuid4(), uuid4(), uuid4()
    repository.active_memberships.add(target_member)
    repository.sources[("task", task_id)] = EvidenceSourceSnapshot(
        resource_type="task",
        resource_id=task_id,
        version=4,
        completed=True,
        subject_membership_id=other_member,
    )

    with pytest.raises(PeopleSkillReferenceError):
        await _service(repository).record_work_outcome_evidence(
            actor=actor,
            membership_id=target_member,
            evidence=WorkOutcomeEvidenceDraft.create(
                evidence_type="COMPLETED_TASK",
                summary="Someone else's delivery",
                source_resource_type="task",
                source_resource_id=task_id,
                source_resource_version=4,
                observed_at=datetime(2026, 8, 26, tzinfo=UTC),
            ),
            request_id="work-evidence-3",
            idempotency_key="work-evidence-key3",
        )


@pytest.mark.asyncio
async def test_person_skill_rejects_more_than_twenty_evidence_items() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    employee_id = uuid4()
    repository.active_memberships.add(employee_id)
    evidence = tuple(
        SkillEvidenceDraft.create(
            evidence_type="MANAGER_NOTE",
            summary=f"Evidence {index}",
            source_resource_type="review",
            source_resource_id=uuid4(),
            occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
        )
        for index in range(21)
    )

    with pytest.raises(InvalidEvidenceFieldError):
        await _service(repository).set_person_skill(
            actor=actor,
            membership_id=employee_id,
            skill_id=repository.skill.id,
            level=4,
            evidence=evidence,
            expected_version=None,
            request_id="person-skill-evidence-limit",
            idempotency_key="person-skill-evidence-limit-key",
        )


@pytest.mark.asyncio
async def test_person_skill_derives_manager_note_provenance_from_the_writer() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    member_id = uuid4()
    repository.active_memberships.add(member_id)

    await _service(repository).set_person_skill(
        actor=actor,
        membership_id=member_id,
        skill_id=repository.skill.id,
        level=4,
        evidence=(SkillEvidenceDraft.create(
            evidence_type="MANAGER_NOTE",
            summary="Observed delivery",
            source_resource_type="untrusted",
            source_resource_id=uuid4(),
            occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),),
        expected_version=None,
        request_id="manager-note-derived",
        idempotency_key="manager-note-derived-key",
    )

    draft = next(
        values["draft"]
        for name, values in repository.calls
        if name == "upsert_person_skill"
    )
    assert draft.evidence[0].source_resource_type == "manager_note"
    assert draft.evidence[0].source_resource_id == actor.membership_id


@pytest.mark.asyncio
async def test_person_skill_rejects_certificate_without_a_verified_source_adapter() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    member_id = uuid4()
    repository.active_memberships.add(member_id)

    with pytest.raises(PeopleSkillReferenceError, match="evidence_type"):
        await _service(repository).set_person_skill(
            actor=actor,
            membership_id=member_id,
            skill_id=repository.skill.id,
            level=4,
            evidence=(
                SkillEvidenceDraft.create(
                    evidence_type="CERTIFICATE",
                    summary="Unverified certificate",
                    source_resource_type="certificate",
                    source_resource_id=uuid4(),
                    occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
                ),
            ),
            expected_version=None,
            request_id="certificate-deferred",
            idempotency_key="certificate-deferred-key",
        )

    assert not any(name == "upsert_person_skill" for name, _ in repository.calls)


@pytest.mark.asyncio
async def test_person_skill_mutation_locks_mutable_membership_and_skill_references() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    member_id = uuid4()
    repository.active_memberships.add(member_id)

    await _service(repository).set_person_skill(
        actor=actor,
        membership_id=member_id,
        skill_id=repository.skill.id,
        level=4,
        evidence=(),
        expected_version=None,
        request_id="locked-references",
        idempotency_key="locked-references-key",
    )

    skill_call = next(values for name, values in repository.calls if name == "get_skill")
    membership_call = next(
        values for name, values in repository.calls if name == "membership_is_active"
    )
    assert membership_call["for_update"] is True
    assert skill_call["for_update"] is True


@pytest.mark.asyncio
async def test_only_writers_list_inactive_person_skill_tombstones() -> None:
    manager = _actor()
    manager_repository = FakeRepository(manager)
    member_id = uuid4()
    manager_repository.active_memberships.add(member_id)

    await _service(manager_repository).list_person_skills(
        actor=manager, membership_id=member_id
    )
    manager_call = next(
        values for name, values in manager_repository.calls if name == "list_person_skills"
    )
    assert manager_call["include_inactive"] is True

    employee = _actor(MembershipRole.EMPLOYEE)
    employee_repository = FakeRepository(employee)
    employee_repository.active_memberships.add(member_id)
    await _service(employee_repository).list_person_skills(
        actor=employee, membership_id=member_id
    )
    employee_call = next(
        values for name, values in employee_repository.calls if name == "list_person_skills"
    )
    assert employee_call["include_inactive"] is False


@pytest.mark.asyncio
async def test_person_skill_replay_precedes_mutable_reference_checks() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    replay = PeopleMutationResult(resource=object(), replayed=True)
    repository.person_skill_replay = replay

    result = await _service(repository).set_person_skill(
        actor=actor,
        membership_id=uuid4(),
        skill_id=repository.skill.id,
        level=4,
        evidence=(),
        expected_version=None,
        request_id="person-skill-replay",
        idempotency_key="person-skill-replay-key",
    )

    assert result is replay
    assert not any(name == "membership_is_active" for name, _ in repository.calls)


@pytest.mark.asyncio
async def test_work_evidence_replay_precedes_mutable_reference_checks() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    replay = PeopleMutationResult(resource=object(), replayed=True)
    repository.work_evidence_replay = replay

    result = await _service(repository).record_work_outcome_evidence(
        actor=actor,
        membership_id=uuid4(),
        evidence=WorkOutcomeEvidenceDraft.create(
            evidence_type="COMPLETED_TASK",
            summary="Original result",
            source_resource_type="task",
            source_resource_id=uuid4(),
            source_resource_version=4,
            observed_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        request_id="work-evidence-replay",
        idempotency_key="work-evidence-replay-key",
    )

    assert result is replay
    assert not any(name == "membership_is_active" for name, _ in repository.calls)


@pytest.mark.asyncio
async def test_person_skill_locks_task_sources_in_deterministic_order() -> None:
    actor = _actor()
    repository = FakeRepository(actor)
    employee_id = uuid4()
    repository.active_memberships.add(employee_id)
    task_ids = (UUID(int=2), UUID(int=1))
    for task_id in task_ids:
        repository.sources[("task", task_id)] = EvidenceSourceSnapshot(
            resource_type="task",
            resource_id=task_id,
            version=1,
            completed=True,
            subject_membership_id=employee_id,
        )
    evidence = tuple(
        SkillEvidenceDraft.create(
            evidence_type="COMPLETED_TASK",
            summary=f"Task {task_id}",
            source_resource_type="task",
            source_resource_id=task_id,
            occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
        )
        for task_id in task_ids
    )

    await _service(repository).set_person_skill(
        actor=actor,
        membership_id=employee_id,
        skill_id=repository.skill.id,
        level=4,
        evidence=evidence,
        expected_version=None,
        request_id="person-skill-lock-order",
        idempotency_key="person-skill-lock-order-key",
    )

    locked_ids = [
        values["resource_id"] for name, values in repository.calls if name == "get_evidence_source"
    ]
    assert locked_ids == [UUID(int=1), UUID(int=2)]
