"""Repository integration tests for idempotent, audited People Skills writes."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.database import create_database_engine, create_session_factory
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.adapters.repository import (
    SqlAlchemyPeopleCapacityTransactionFactory,
)
from app.modules.people_capacity.domain.skills import (
    PeopleSkillIdempotencyKeyReusedError,
    PeopleSkillVersionMismatchError,
    PersonSkillDraft,
    SkillDraft,
    SkillEvidenceDraft,
    WorkOutcomeEvidenceDraft,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 with local PostgreSQL running",
    ),
]


def _actor(organization_id: UUID, membership_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Manager",
        membership_id=membership_id,
        organization_id=organization_id,
        organization_name="People Test",
        role=MembershipRole.MANAGER,
    )


async def _seed_members(
    engine: AsyncEngine,
    *,
    organization_id: UUID,
    memberships: tuple[tuple[UUID, MembershipRole], ...],
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, 'People Test')"),
            {"id": organization_id, "slug": f"people-repo-{organization_id.hex}"},
        )
        for membership_id, role in memberships:
            user_id = uuid4()
            email = f"{user_id.hex}@example.test"
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'Person', 'hash')"
                ),
                {"id": user_id, "email": email},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :organization_id, :user_id, :role)"
                ),
                {
                    "id": membership_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "role": role.value,
                },
            )


@pytest.mark.asyncio
async def test_skill_create_is_idempotent_versioned_and_audited() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, manager_id = uuid4(), uuid4()
    actor = _actor(organization_id, manager_id)
    factory = SqlAlchemyPeopleCapacityTransactionFactory(create_session_factory(engine))
    draft = SkillDraft.create(name="Delivery Planning", description="Plan delivery work")

    try:
        await _seed_members(
            engine,
            organization_id=organization_id,
            memberships=((manager_id, MembershipRole.MANAGER),),
        )
        async with factory() as repository:
            created = await repository.create_skill(
                actor=actor,
                draft=draft,
                request_id="skill-create-1",
                idempotency_key="skill-create-key",
                request_fingerprint="a" * 64,
            )
        async with factory() as repository:
            replayed = await repository.create_skill(
                actor=actor,
                draft=draft,
                request_id="skill-create-2",
                idempotency_key="skill-create-key",
                request_fingerprint="a" * 64,
            )

        assert created.replayed is False
        assert replayed.replayed is True
        assert replayed.resource == created.resource
        assert created.resource.version == 1

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM skills WHERE organization_id = :organization_id"),
                    {"organization_id": organization_id},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM skill_versions "
                        "WHERE organization_id = :organization_id AND skill_id = :skill_id"
                    ),
                    {"organization_id": organization_id, "skill_id": created.resource.id},
                )
                == 1
            )
            audit = (
                await connection.execute(
                    text(
                        "SELECT before_data, after_data FROM audit_events "
                        "WHERE organization_id = :organization_id "
                        "AND action = 'people.skill.created' AND resource_id = :resource_id"
                    ),
                    {
                        "organization_id": organization_id,
                        "resource_id": created.resource.id,
                    },
                )
            ).one()
            assert audit.before_data == {}
            assert audit.after_data == {
                "active": True,
                "description": "Plan delivery work",
                "name": "Delivery Planning",
                "normalized_name": "delivery planning",
                "version": 1,
            }

        async with factory() as repository:
            with pytest.raises(PeopleSkillIdempotencyKeyReusedError):
                await repository.create_skill(
                    actor=actor,
                    draft=SkillDraft.create(name="Different", description=None),
                    request_id="skill-create-3",
                    idempotency_key="skill-create-key",
                    request_fingerprint="b" * 64,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_person_skill_upsert_is_versioned_and_audits_only_safe_evidence_ids() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, manager_id, employee_id = uuid4(), uuid4(), uuid4()
    actor = _actor(organization_id, manager_id)
    factory = SqlAlchemyPeopleCapacityTransactionFactory(create_session_factory(engine))

    try:
        await _seed_members(
            engine,
            organization_id=organization_id,
            memberships=(
                (manager_id, MembershipRole.MANAGER),
                (employee_id, MembershipRole.EMPLOYEE),
            ),
        )
        async with factory() as repository:
            skill = (
                await repository.create_skill(
                    actor=actor,
                    draft=SkillDraft.create(name="Facilitation", description=None),
                    request_id="person-skill-seed",
                    idempotency_key="person-skill-seed-key",
                    request_fingerprint="c" * 64,
                )
            ).resource

        first_evidence = SkillEvidenceDraft.create(
            evidence_type="MANAGER_NOTE",
            summary="Sensitive narrative must not enter audit",
            source_resource_type="review",
            source_resource_id=uuid4(),
            occurred_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
        async with factory() as repository:
            created = await repository.upsert_person_skill(
                actor=actor,
                draft=PersonSkillDraft.create(
                    membership_id=employee_id,
                    skill_id=skill.id,
                    level=3,
                    verified_by_membership_id=manager_id,
                    evidence=(first_evidence,),
                ),
                expected_version=None,
                request_id="person-skill-create",
                idempotency_key="person-skill-create-key",
                request_fingerprint="d" * 64,
            )
        async with factory() as repository:
            updated = await repository.upsert_person_skill(
                actor=actor,
                draft=PersonSkillDraft.create(
                    membership_id=employee_id,
                    skill_id=skill.id,
                    level=4,
                    verified_by_membership_id=manager_id,
                    evidence=(),
                ),
                expected_version=1,
                request_id="person-skill-update",
                idempotency_key="person-skill-update-key",
                request_fingerprint="e" * 64,
            )

        assert created.resource.version == 1
        assert updated.resource.version == 2
        assert updated.resource.level.value == 4

        async with factory() as repository:
            replayed = await repository.upsert_person_skill(
                actor=actor,
                draft=PersonSkillDraft.create(
                    membership_id=employee_id,
                    skill_id=skill.id,
                    level=4,
                    verified_by_membership_id=manager_id,
                    evidence=(),
                ),
                expected_version=1,
                request_id="person-skill-update-replay",
                idempotency_key="person-skill-update-key",
                request_fingerprint="e" * 64,
            )
        assert replayed.replayed is True
        assert replayed.resource == updated.resource

        async with factory() as repository:
            with pytest.raises(PeopleSkillVersionMismatchError) as error:
                await repository.upsert_person_skill(
                    actor=actor,
                    draft=PersonSkillDraft.create(
                        membership_id=employee_id,
                        skill_id=skill.id,
                        level=5,
                        verified_by_membership_id=manager_id,
                        evidence=(),
                    ),
                    expected_version=1,
                    request_id="person-skill-stale",
                    idempotency_key="person-skill-stale-key",
                    request_fingerprint="f" * 64,
                )
        assert error.value.current_version == 2

        async with engine.connect() as connection:
            evidence_ids = list(
                await connection.scalars(
                    text(
                        "SELECT id FROM skill_evidence "
                        "WHERE organization_id = :organization_id AND person_skill_id = :id"
                    ),
                    {"organization_id": organization_id, "id": created.resource.id},
                )
            )
            audit_after = await connection.scalar(
                text(
                    "SELECT after_data FROM audit_events "
                    "WHERE organization_id = :organization_id "
                    "AND action = 'people.person_skill.created' AND resource_id = :id"
                ),
                {"organization_id": organization_id, "id": created.resource.id},
            )
            assert audit_after == {
                "active": True,
                "evidence_ids": [str(evidence_ids[0])],
                "level": 3,
                "skill_id": str(skill.id),
                "verified_by_membership_id": str(manager_id),
                "version": 1,
            }
            assert "Sensitive narrative" not in str(audit_after)

            updated_audit = (
                await connection.execute(
                    text(
                        "SELECT before_data, after_data FROM audit_events "
                        "WHERE organization_id = :organization_id "
                        "AND action = 'people.person_skill.updated' AND resource_id = :id"
                    ),
                    {"organization_id": organization_id, "id": created.resource.id},
                )
            ).one()
            expected_evidence_ids = [str(evidence_ids[0])]
            assert updated_audit.before_data == {
                "active": True,
                "evidence_ids": expected_evidence_ids,
                "level": 3,
                "skill_id": str(skill.id),
                "verified_by_membership_id": str(manager_id),
                "version": 1,
            }
            assert updated_audit.after_data == {
                "active": True,
                "evidence_ids": expected_evidence_ids,
                "level": 4,
                "skill_id": str(skill.id),
                "verified_by_membership_id": str(manager_id),
                "version": 2,
            }
            assert "Sensitive narrative" not in str(updated_audit)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_skill_create_with_same_key_commits_once_and_replays() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, manager_id = uuid4(), uuid4()
    actor = _actor(organization_id, manager_id)
    factory = SqlAlchemyPeopleCapacityTransactionFactory(create_session_factory(engine))
    draft = SkillDraft.create(name="Concurrent Planning", description=None)

    async def create_once(request_id: str):
        async with factory() as repository:
            return await repository.create_skill(
                actor=actor,
                draft=draft,
                request_id=request_id,
                idempotency_key="concurrent-skill-key",
                request_fingerprint="9" * 64,
            )

    try:
        await _seed_members(
            engine,
            organization_id=organization_id,
            memberships=((manager_id, MembershipRole.MANAGER),),
        )
        first, second = await asyncio.gather(
            create_once("concurrent-1"), create_once("concurrent-2")
        )

        assert {first.replayed, second.replayed} == {False, True}
        assert first.resource == second.resource
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM skills "
                        "WHERE organization_id = :organization_id AND normalized_name = :name"
                    ),
                    {"organization_id": organization_id, "name": draft.normalized_name},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM audit_events "
                        "WHERE organization_id = :organization_id "
                        "AND action = 'people.skill.created' AND resource_id = :resource_id"
                    ),
                    {
                        "organization_id": organization_id,
                        "resource_id": first.resource.id,
                    },
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_person_skill_upsert_claims_key_before_stale_checks() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, manager_id, employee_id = uuid4(), uuid4(), uuid4()
    actor = _actor(organization_id, manager_id)
    factory = SqlAlchemyPeopleCapacityTransactionFactory(create_session_factory(engine))

    try:
        await _seed_members(
            engine,
            organization_id=organization_id,
            memberships=(
                (manager_id, MembershipRole.MANAGER),
                (employee_id, MembershipRole.EMPLOYEE),
            ),
        )
        async with factory() as repository:
            skill = (
                await repository.create_skill(
                    actor=actor,
                    draft=SkillDraft.create(name="Concurrent Facilitation", description=None),
                    request_id="concurrent-person-seed",
                    idempotency_key="concurrent-person-seed-key",
                    request_fingerprint="7" * 64,
                )
            ).resource

        async with factory() as repository:
            seeded = await repository.upsert_person_skill(
                actor=actor,
                draft=PersonSkillDraft.create(
                    membership_id=employee_id,
                    skill_id=skill.id,
                    level=3,
                    verified_by_membership_id=manager_id,
                    evidence=(),
                ),
                expected_version=None,
                request_id="concurrent-person-level-seed",
                idempotency_key="concurrent-person-level-seed-key",
                request_fingerprint="6" * 64,
            )
        assert seeded.resource.version == 1

        draft = PersonSkillDraft.create(
            membership_id=employee_id,
            skill_id=skill.id,
            level=4,
            verified_by_membership_id=manager_id,
            evidence=(),
        )

        async def upsert_once(request_id: str):
            async with factory() as repository:
                return await repository.upsert_person_skill(
                    actor=actor,
                    draft=draft,
                    expected_version=1,
                    request_id=request_id,
                    idempotency_key="concurrent-person-key",
                    request_fingerprint="8" * 64,
                )

        first, second = await asyncio.gather(
            upsert_once("concurrent-person-1"),
            upsert_once("concurrent-person-2"),
        )

        assert {first.replayed, second.replayed} == {False, True}
        assert first.resource == second.resource
        assert first.resource.version == 2
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM person_skills "
                        "WHERE organization_id = :organization_id "
                        "AND membership_id = :membership_id AND skill_id = :skill_id"
                    ),
                    {
                        "organization_id": organization_id,
                        "membership_id": employee_id,
                        "skill_id": skill.id,
                    },
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM audit_events "
                        "WHERE organization_id = :organization_id "
                        "AND action = 'people.person_skill.updated' "
                        "AND resource_id = :resource_id"
                    ),
                    {
                        "organization_id": organization_id,
                        "resource_id": first.resource.id,
                    },
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_work_outcome_evidence_is_idempotent_and_audit_omits_summary() -> None:
    engine = create_database_engine(Settings(environment="test"))
    organization_id, manager_id, employee_id = uuid4(), uuid4(), uuid4()
    project_id, task_id = uuid4(), uuid4()
    actor = _actor(organization_id, manager_id)
    factory = SqlAlchemyPeopleCapacityTransactionFactory(create_session_factory(engine))

    try:
        await _seed_members(
            engine,
            organization_id=organization_id,
            memberships=(
                (manager_id, MembershipRole.MANAGER),
                (employee_id, MembershipRole.EMPLOYEE),
            ),
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, created_by_membership_id, "
                    "updated_by_membership_id) VALUES "
                    "(:id, :organization_id, 'Evidence Project', :actor, :actor)"
                ),
                {"id": project_id, "organization_id": organization_id, "actor": manager_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO tasks "
                    "(id, organization_id, project_id, title, assignee_membership_id, status, "
                    "version, created_by_membership_id, updated_by_membership_id) VALUES "
                    "(:id, :organization_id, :project_id, 'Completed work', :employee_id, "
                    "'DONE', 3, :actor, :actor)"
                ),
                {
                    "id": task_id,
                    "organization_id": organization_id,
                    "project_id": project_id,
                    "employee_id": employee_id,
                    "actor": manager_id,
                },
            )
        draft = WorkOutcomeEvidenceDraft.create(
            evidence_type="COMPLETED_TASK",
            summary="Private outcome narrative",
            source_resource_type="task",
            source_resource_id=task_id,
            source_resource_version=3,
            observed_at=datetime(2026, 8, 25, tzinfo=UTC),
        )

        async with factory() as repository:
            created = await repository.record_work_outcome_evidence(
                actor=actor,
                membership_id=employee_id,
                draft=draft,
                request_id="work-evidence-create",
                idempotency_key="work-evidence-key",
                request_fingerprint="1" * 64,
            )
        async with factory() as repository:
            replayed = await repository.record_work_outcome_evidence(
                actor=actor,
                membership_id=employee_id,
                draft=draft,
                request_id="work-evidence-replay",
                idempotency_key="work-evidence-key",
                request_fingerprint="1" * 64,
            )

        assert created.replayed is False
        assert replayed.replayed is True
        assert replayed.resource == created.resource
        async with engine.connect() as connection:
            audit_after = await connection.scalar(
                text(
                    "SELECT after_data FROM audit_events "
                    "WHERE organization_id = :organization_id "
                    "AND action = 'people.work_outcome_evidence.created' "
                    "AND resource_id = :resource_id"
                ),
                {
                    "organization_id": organization_id,
                    "resource_id": created.resource.id,
                },
            )
            assert audit_after == {
                "evidence_type": "COMPLETED_TASK",
                "membership_id": str(employee_id),
                "source_resource_id": str(task_id),
                "source_resource_type": "task",
                "source_resource_version": 3,
            }
            assert "Private outcome narrative" not in str(audit_after)
    finally:
        await engine.dispose()
