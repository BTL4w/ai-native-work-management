"""Service behavior for append-only project team requirement snapshots."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.domain.skills import SkillLevel
from app.modules.work.domain.tasks import TaskStatus
from app.modules.work.planning.assignment.adapters.repository import (
    SqlAlchemyTeamRequirementRepository,
)
from app.modules.work.planning.assignment.application.requirement_service import (
    ConfirmRequirementsCommand,
    DeriveRequirementsCommand,
    InMemoryTeamRequirementRepository,
    RefreshRequirementsCommand,
    RequirementItem,
    RequirementItemInput,
    RequirementSet,
    ReviseRequirementsCommand,
    TeamRequirementForbiddenError,
    TeamRequirementIdempotencyKeyReusedError,
    TeamRequirementIncompleteError,
    TeamRequirementNotFoundError,
    TeamRequirementReferenceError,
    TeamRequirementService,
    TeamRequirementStatus,
    TeamRequirementVersionMismatchError,
)

_TASK_A = uuid4()
_TASK_B = uuid4()


def _actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Manager",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Tenant",
        role=role,
    )


def _item(actor: AuthenticatedActor) -> RequirementItemInput:
    return RequirementItemInput(
        skill_id=uuid4(),
        minimum_level=SkillLevel.LEVEL_2,
        project_week_id=uuid4(),
        effort_hours=8,
        source_task_ids=(uuid4(),),
    )


@pytest.mark.asyncio
async def test_manager_revises_by_appending_a_new_immutable_version() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)
    draft = await service.derive(
        DeriveRequirementsCommand(
            actor=actor,
            project_id=uuid4(),
            request_id="request",
            idempotency_key="a" * 16,
            items=(_item(actor),),
            incomplete_items=(),
        )
    )

    revised = await service.revise(
        ReviseRequirementsCommand(
            actor=actor,
            project_id=draft.project_id,
            requirement_set_id=draft.id,
            expected_version=draft.version,
            request_id="request-2",
            idempotency_key="b" * 16,
            items=(_item(actor),),
            incomplete_items=(),
        )
    )

    assert revised.version == 2
    assert repository.version_count(draft.id) == 2
    assert repository.audit_actions[-1] == "team_requirement.revised"


@pytest.mark.asyncio
async def test_refresh_rederives_current_task_facts_instead_of_reusing_stale_items() -> None:
    actor = _actor()
    project_id = uuid4()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)
    original = _item(actor)
    draft = await service.derive(
        DeriveRequirementsCommand(actor, project_id, "derive", "a" * 16, (original,), ())
    )
    replacement = replace(original, effort_hours=21)
    repository.set_derived_requirements(project_id, (replacement,), ())

    refreshed = await service.refresh(
        RefreshRequirementsCommand(actor, project_id, draft.id, draft.version, "refresh", "b" * 16)
    )

    assert refreshed.version == 2
    assert refreshed.status is TeamRequirementStatus.DRAFT
    assert refreshed.items[0].effort_hours == 21
    assert repository.audit_actions[-1] == "team_requirement.refreshed"


@pytest.mark.asyncio
async def test_employee_mutation_is_denied_and_audited() -> None:
    actor = _actor(MembershipRole.EMPLOYEE)
    repository = InMemoryTeamRequirementRepository(project_managers=set())
    service = TeamRequirementService(lambda: repository)

    with pytest.raises(TeamRequirementForbiddenError):
        await service.derive(
            DeriveRequirementsCommand(
                actor=actor,
                project_id=uuid4(),
                request_id="request",
                idempotency_key="a" * 16,
                items=(_item(actor),),
                incomplete_items=(),
            )
        )

    assert repository.audit_actions == ["team_requirement.derive.rejected"]


@pytest.mark.asyncio
async def test_confirmation_rejects_incomplete_and_audits_rejection() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)
    draft = await service.derive(
        DeriveRequirementsCommand(
            actor=actor,
            project_id=uuid4(),
            request_id="request",
            idempotency_key="a" * 16,
            items=(),
            incomplete_items=((uuid4(), "REQUIRED_SKILL_MISSING"),),
        )
    )

    with pytest.raises(TeamRequirementIncompleteError):
        await service.confirm(
            ConfirmRequirementsCommand(
                actor=actor,
                project_id=draft.project_id,
                requirement_set_id=draft.id,
                expected_version=draft.version,
                request_id="request-2",
                idempotency_key="b" * 16,
            )
        )

    assert repository.audit_actions.count("team_requirement.confirm.rejected") == 1
    assert repository.version_count(draft.id) == 1


@pytest.mark.asyncio
async def test_idempotent_revision_replays_original_snapshot_for_equivalent_item_order() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)
    draft = await service.derive(
        DeriveRequirementsCommand(
            actor=actor,
            project_id=uuid4(),
            request_id="derive",
            idempotency_key="a" * 16,
            items=(_item(actor),),
            incomplete_items=(),
        )
    )
    first, second = _item(actor), _item(actor)
    first = RequirementItemInput(
        first.skill_id,
        first.minimum_level,
        first.project_week_id,
        first.effort_hours,
        tuple(reversed(first.source_task_ids)),
    )
    command = ReviseRequirementsCommand(
        actor, draft.project_id, draft.id, 1, "revise", "b" * 16, (first, second), ()
    )
    revised = await service.revise(command)
    replayed = await service.revise(
        ReviseRequirementsCommand(
            actor, draft.project_id, draft.id, 1, "another", "b" * 16, (second, first), ()
        )
    )

    assert replayed.replayed is True
    assert replayed.version == revised.version == 2


@pytest.mark.asyncio
async def test_reference_rejection_is_audited_once_without_a_partial_version() -> None:
    actor = _actor()
    project_id = uuid4()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)
    draft = await service.derive(
        DeriveRequirementsCommand(actor, project_id, "derive", "a" * 16, (_item(actor),), ())
    )

    with pytest.raises(TeamRequirementReferenceError):
        await service.derive(
            DeriveRequirementsCommand(actor, project_id, "duplicate", "b" * 16, (_item(actor),), ())
        )

    assert repository.version_count(draft.id) == 1
    assert repository.audit_actions.count("team_requirement.derive.rejected") == 1


@pytest.mark.asyncio
async def test_version_mismatch_is_audited_once_without_a_partial_version() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)
    draft = await service.derive(
        DeriveRequirementsCommand(actor, uuid4(), "derive", "a" * 16, (_item(actor),), ())
    )

    with pytest.raises(TeamRequirementVersionMismatchError):
        await service.revise(
            ReviseRequirementsCommand(
                actor,
                draft.project_id,
                draft.id,
                99,
                "stale",
                "b" * 16,
                (_item(actor),),
                (),
            )
        )

    assert repository.version_count(draft.id) == 1
    assert repository.audit_actions.count("team_requirement.revise.rejected") == 1


@pytest.mark.asyncio
async def test_not_found_mutation_is_audited_once_without_a_partial_version() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)

    with pytest.raises(TeamRequirementNotFoundError):
        await service.revise(
            ReviseRequirementsCommand(
                actor,
                uuid4(),
                uuid4(),
                1,
                "missing",
                "b" * 16,
                (_item(actor),),
                (),
            )
        )

    assert repository.audit_actions == ["team_requirement.revise.rejected"]


@pytest.mark.asyncio
async def test_idempotency_key_reuse_is_audited_once_without_a_partial_version() -> None:
    actor = _actor()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)
    draft = await service.derive(
        DeriveRequirementsCommand(actor, uuid4(), "derive", "a" * 16, (_item(actor),), ())
    )
    await service.revise(
        ReviseRequirementsCommand(
            actor,
            draft.project_id,
            draft.id,
            1,
            "revise",
            "b" * 16,
            (_item(actor),),
            (),
        )
    )

    with pytest.raises(TeamRequirementIdempotencyKeyReusedError):
        await service.revise(
            ReviseRequirementsCommand(
                actor,
                draft.project_id,
                draft.id,
                1,
                "reuse",
                "b" * 16,
                (_item(actor), _item(actor)),
                (),
            )
        )

    assert repository.version_count(draft.id) == 2
    assert repository.audit_actions.count("team_requirement.revise.rejected") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", [Decimal("0.5"), Decimal("1.5")])
async def test_fractional_derived_effort_fails_closed_without_persistence(
    effort: Decimal,
) -> None:
    actor = _actor()
    project_id = uuid4()
    repository = InMemoryTeamRequirementRepository(project_managers={actor.membership_id})
    service = TeamRequirementService(lambda: repository)

    with pytest.raises(TeamRequirementReferenceError):
        invalid = RequirementItemInput(
            skill_id=uuid4(),
            minimum_level=SkillLevel.LEVEL_1,
            project_week_id=uuid4(),
            effort_hours=cast(int, effort),
            source_task_ids=(uuid4(),),
        )
        await service.derive(
            DeriveRequirementsCommand(actor, project_id, "fractional", "a" * 16, (invalid,), ())
        )

    assert await repository.get_for_project(actor=actor, project_id=project_id) is None


class _DeriveSession:
    def __init__(self, skill_id: object) -> None:
        self.scalar_values = [None, SimpleNamespace(id=skill_id)]
        self.added: list[object] = []

    async def scalar(self, _query: object) -> object | None:
        return self.scalar_values.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", [Decimal("0.5"), Decimal("1.5")])
async def test_sql_derivation_rejects_fractional_effort_before_persisting_a_root(
    monkeypatch: pytest.MonkeyPatch,
    effort: Decimal,
) -> None:
    actor = _actor()
    project_id, week_id, task_id, skill_id = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    task = SimpleNamespace(
        id=task_id,
        organization_id=actor.organization_id,
        project_id=project_id,
        milestone_id=None,
        title="Fractional effort",
        description=None,
        assignee_membership_id=None,
        status=TaskStatus.TO_DO,
        due_date=None,
        version=1,
        created_at=now,
        updated_at=now,
        project_week_id=week_id,
        required_skill_labels=["facilitation"],
        estimated_effort_hours=effort,
    )
    session = _DeriveSession(skill_id)
    repository = SqlAlchemyTeamRequirementRepository(cast(Any, session))
    record = SimpleNamespace(state=None, response_status=None, response_body=None)

    async def claim(*_args: object, **_kwargs: object) -> tuple[object, None]:
        return record, None

    async def project_tasks(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        return (task,)

    monkeypatch.setattr(repository, "_activate", _no_op)
    monkeypatch.setattr(repository, "_project", _no_op)
    monkeypatch.setattr(repository, "_claim", claim)
    monkeypatch.setattr(repository, "_project_task_models", project_tasks)

    with pytest.raises(TeamRequirementReferenceError, match="effort_hours"):
        await repository.derive(
            DeriveRequirementsCommand(actor, project_id, "fractional", "a" * 16)
        )

    assert session.added == []


class _VersionWriteSession:
    def __init__(self, root: SimpleNamespace) -> None:
        self.root = root
        self.events: list[tuple[str, object]] = []

    def add(self, _value: object) -> None:
        self.events.append(("add", self.root.current_version))

    async def flush(self) -> None:
        self.events.append(("flush", self.root.current_version))


@pytest.mark.asyncio
async def test_version_is_inserted_before_the_root_pointer_is_populated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    now = datetime.now(UTC)
    root = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        current_version=None,
        status=TeamRequirementStatus.DRAFT.value,
        version=1,
        updated_by_membership_id=actor.membership_id,
        created_at=now,
        updated_at=now,
    )
    session = _VersionWriteSession(root)
    repository = SqlAlchemyTeamRequirementRepository(cast(Any, session))

    async def validate_inputs(*_args: object, **_kwargs: object) -> dict[object, int]:
        return {}

    monkeypatch.setattr(repository, "_validate_inputs", validate_inputs)
    monkeypatch.setattr(repository, "_validate_incomplete_items", _no_op)

    await repository._write_version(  # pyright: ignore[reportPrivateUsage]
        actor=actor,
        set_model=cast(Any, root),
        version=1,
        status=TeamRequirementStatus.DRAFT,
        items=(),
        incomplete=(),
        task_provenance=(),
    )

    assert session.events == [("add", None), ("flush", None)]
    assert root.current_version == 1


class _ConfirmSession:
    def __init__(self, root: SimpleNamespace) -> None:
        self.root = root
        self.added: list[object] = []

    async def scalar(self, _query: object) -> object:
        return self.root

    def add(self, value: object) -> None:
        self.added.append(value)


async def _no_op(*_args: object, **_kwargs: object) -> None:
    return None


def _requirement_set(
    actor: AuthenticatedActor,
    *,
    project_id: Any,
    set_id: Any,
    status: TeamRequirementStatus = TeamRequirementStatus.DRAFT,
) -> RequirementSet:
    now = datetime.now(UTC)
    return RequirementSet(
        id=set_id,
        organization_id=actor.organization_id,
        project_id=project_id,
        version=2,
        status=status,
        items=(
            RequirementItem(
                uuid4(),
                uuid4(),
                SkillLevel.LEVEL_5,
                uuid4(),
                13,
                (uuid4(),),
            ),
            RequirementItem(
                uuid4(),
                uuid4(),
                SkillLevel.LEVEL_3,
                uuid4(),
                5,
                (uuid4(),),
            ),
        ),
        incomplete_items=(),
        created_at=now,
        updated_at=now,
    )


async def _exercise_sql_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stored_provenance: tuple[tuple[Any, int], ...],
    current_provenance: tuple[tuple[Any, int], ...],
    derived_matches_current: bool = False,
) -> tuple[RequirementSet, dict[str, object], _ConfirmSession]:
    actor = _actor()
    project_id, set_id = uuid4(), uuid4()
    root = SimpleNamespace(id=set_id, project_id=project_id, version=2)
    session = _ConfirmSession(root)
    repository = SqlAlchemyTeamRequirementRepository(cast(Any, session))
    current = _requirement_set(actor, project_id=project_id, set_id=set_id)
    record = SimpleNamespace(state=None, response_status=None, response_body=None)
    captured: dict[str, object] = {}

    async def claim(*_args: object, **_kwargs: object) -> tuple[object, None]:
        return record, None

    async def get_current(*_args: object, **_kwargs: object) -> RequirementSet:
        return current

    async def derive_defaults(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        selected = current.items if derived_matches_current else current.items[:1]
        return (
            tuple(
                RequirementItemInput(
                    item.skill_id,
                    item.minimum_level if derived_matches_current else SkillLevel.LEVEL_1,
                    item.project_week_id,
                    item.effort_hours if derived_matches_current else 8,
                    item.source_task_ids,
                )
                for item in selected
            ),
            (),
        )

    async def stored(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        return stored_provenance

    async def project_tasks(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        return current_provenance

    async def write(**values: object) -> RequirementSet:
        captured.update(values)
        return RequirementSet(
            id=current.id,
            organization_id=current.organization_id,
            project_id=current.project_id,
            version=cast(int, values["version"]),
            status=cast(TeamRequirementStatus, values["status"]),
            items=current.items,
            incomplete_items=current.incomplete_items,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )

    monkeypatch.setattr(repository, "_activate", _no_op)
    monkeypatch.setattr(repository, "_project", _no_op)
    monkeypatch.setattr(repository, "_claim", claim)
    monkeypatch.setattr(repository, "_get_by_set", get_current)
    monkeypatch.setattr(repository, "_derive_inputs", derive_defaults)
    monkeypatch.setattr(repository, "_stored_task_provenance", stored, raising=False)
    monkeypatch.setattr(repository, "_project_task_provenance", project_tasks, raising=False)
    monkeypatch.setattr(repository, "_write_version", write)

    result = await repository.confirm(
        ConfirmRequirementsCommand(actor, project_id, set_id, 2, "confirm", "c" * 16)
    )
    return result, captured, session


@pytest.mark.asyncio
async def test_confirmation_preserves_manager_edited_snapshot_when_provenance_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    result, captured, _session = await _exercise_sql_confirmation(
        monkeypatch,
        stored_provenance=((task_id, 4),),
        current_provenance=((task_id, 4),),
    )

    items = cast(tuple[RequirementItemInput, ...], captured["items"])
    assert result.status is TeamRequirementStatus.CONFIRMED
    assert [(int(item.minimum_level), item.effort_hours) for item in items] == [(5, 13), (3, 5)]
    assert [item.skill_id for item in items] == [item.skill_id for item in result.items]
    assert [item.project_week_id for item in items] == [
        item.project_week_id for item in result.items
    ]
    assert [item.source_task_ids for item in items] == [
        item.source_task_ids for item in result.items
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_provenance", "current_provenance"),
    [
        (((_TASK_A, 1),), ((_TASK_A, 1), (_TASK_B, 1))),
        (((_TASK_A, 1), (_TASK_B, 1)), ((_TASK_A, 1),)),
        (((_TASK_A, 1),), ((_TASK_A, 2),)),
    ],
    ids=("task-added", "task-removed", "task-version-changed"),
)
async def test_confirmation_marks_added_removed_or_version_changed_task_provenance_stale(
    monkeypatch: pytest.MonkeyPatch,
    stored_provenance: tuple[tuple[Any, int], ...],
    current_provenance: tuple[tuple[Any, int], ...],
) -> None:
    result, captured, _session = await _exercise_sql_confirmation(
        monkeypatch,
        stored_provenance=stored_provenance,
        current_provenance=current_provenance,
        derived_matches_current=True,
    )

    assert result.status is TeamRequirementStatus.STALE
    assert cast(TeamRequirementStatus, captured["status"]) is TeamRequirementStatus.STALE


@pytest.mark.asyncio
async def test_stale_snapshot_requires_revision_before_confirmation() -> None:
    actor = _actor()
    project_id, task_id = uuid4(), uuid4()
    repository = InMemoryTeamRequirementRepository(
        project_managers={actor.membership_id},
        project_task_versions={project_id: {task_id: 1}},
    )
    service = TeamRequirementService(lambda: repository)
    item = RequirementItemInput(uuid4(), SkillLevel.LEVEL_2, uuid4(), 8, (task_id,))
    draft = await service.derive(
        DeriveRequirementsCommand(actor, project_id, "derive", "a" * 16, (item,), ())
    )
    repository.set_project_task_versions(project_id, {task_id: 2})
    stale = await service.confirm(
        ConfirmRequirementsCommand(actor, project_id, draft.id, 1, "stale", "b" * 16)
    )

    with pytest.raises(TeamRequirementIncompleteError):
        await service.confirm(
            ConfirmRequirementsCommand(actor, project_id, draft.id, 2, "again", "c" * 16)
        )

    assert stale.status is TeamRequirementStatus.STALE
    assert repository.version_count(draft.id) == 2
    assert repository.audit_actions.count("team_requirement.confirm.rejected") == 1
