"""Framework-independent People Skills domain invariant tests."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.people_capacity.domain.skills import (
    EmptyPersonSkillPatchError,
    EmptySkillPatchError,
    InvalidEvidenceFieldError,
    InvalidSkillFieldError,
    InvalidSkillLevelError,
    PersonSkillDraft,
    PersonSkillPatch,
    Skill,
    SkillDraft,
    SkillEvidenceDraft,
    SkillEvidenceType,
    SkillLevel,
    SkillPatch,
    VerifiedPersonSkill,
    WorkOutcomeEvidenceDraft,
)


def test_skill_draft_preserves_display_name_and_builds_stable_normalized_name() -> None:
    draft = SkillDraft.create(
        name="  Stakeholder   Communication  ",
        description="  Communicate decisions safely.  ",
    )

    assert draft.name == "Stakeholder   Communication"
    assert draft.normalized_name == "stakeholder communication"
    assert draft.description == "Communicate decisions safely."
    assert SkillDraft.create(name="Planning", description="   ").description is None


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_skill_draft_rejects_invalid_name(name: str) -> None:
    with pytest.raises(InvalidSkillFieldError) as error:
        SkillDraft.create(name=name, description=None)

    assert error.value.field == "name"


def test_skill_draft_rejects_oversized_description() -> None:
    with pytest.raises(InvalidSkillFieldError) as error:
        SkillDraft.create(name="Planning", description="x" * 2001)

    assert error.value.field == "description"


def test_skill_patch_distinguishes_omitted_fields_and_applies_one_version() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    skill = Skill(
        id=uuid4(),
        organization_id=uuid4(),
        name="Planning",
        normalized_name="planning",
        description="Initial",
        active=True,
        version=3,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(EmptySkillPatchError):
        SkillPatch.create().validate_not_empty()

    updated = skill.apply(
        SkillPatch.create(
            name="  Program   Planning  ",
            description=None,
            description_supplied=True,
            active=False,
        ),
        updated_at=now,
    )

    assert updated.name == "Program   Planning"
    assert updated.normalized_name == "program planning"
    assert updated.description is None
    assert updated.active is False
    assert updated.version == 4
    with pytest.raises(FrozenInstanceError):
        updated.name = "Mutated"  # type: ignore[misc]


def test_skill_rejects_naive_update_timestamp() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    skill = Skill(
        id=uuid4(),
        organization_id=uuid4(),
        name="Planning",
        normalized_name="planning",
        description=None,
        active=True,
        version=1,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(InvalidSkillFieldError) as error:
        skill.apply(SkillPatch.create(active=False), updated_at=datetime(2026, 8, 26))

    assert error.value.field == "updated_at"


def test_person_skill_requires_level_one_to_five_and_verifier() -> None:
    member_id = uuid4()
    skill_id = uuid4()
    manager_id = uuid4()
    task_id = uuid4()
    now = datetime(2026, 8, 25, tzinfo=UTC)

    draft = PersonSkillDraft.create(
        membership_id=member_id,
        skill_id=skill_id,
        level=5,
        verified_by_membership_id=manager_id,
        evidence=(
            SkillEvidenceDraft.create(
                evidence_type="COMPLETED_TASK",
                summary="  Delivered the approved launch UI  ",
                source_resource_type=" Task ",
                source_resource_id=task_id,
                occurred_at=now,
            ),
        ),
    )

    assert draft.level is SkillLevel.LEVEL_5
    assert draft.verified_by_membership_id == manager_id
    assert draft.evidence[0].evidence_type is SkillEvidenceType.COMPLETED_TASK
    assert draft.evidence[0].summary == "Delivered the approved launch UI"
    assert draft.evidence[0].source_resource_type == "task"


def test_person_skill_factories_copy_evidence_into_immutable_tuples() -> None:
    evidence = [
        SkillEvidenceDraft.create(
            evidence_type="MANAGER_NOTE",
            summary="Observed during review",
            source_resource_type="review",
            source_resource_id=uuid4(),
            occurred_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
    ]
    manager_id = uuid4()

    draft = PersonSkillDraft.create(
        membership_id=uuid4(),
        skill_id=uuid4(),
        level=3,
        verified_by_membership_id=manager_id,
        evidence=evidence,  # type: ignore[arg-type]
    )
    patch = PersonSkillPatch.create(
        verified_by_membership_id=manager_id,
        evidence=evidence,  # type: ignore[arg-type]
    )
    evidence.clear()

    assert isinstance(draft.evidence, tuple)
    assert isinstance(patch.evidence, tuple)
    assert len(draft.evidence) == 1
    assert len(patch.evidence) == 1


@pytest.mark.parametrize("level", [0, 6])
def test_person_skill_rejects_level_outside_range(level: int) -> None:
    with pytest.raises(InvalidSkillLevelError):
        PersonSkillDraft.create(
            membership_id=uuid4(),
            skill_id=uuid4(),
            level=level,
            verified_by_membership_id=uuid4(),
            evidence=(),
        )


@pytest.mark.parametrize("level", [True, 1.0, "3"])
def test_person_skill_rejects_non_integer_level(level: object) -> None:
    with pytest.raises(InvalidSkillLevelError):
        PersonSkillDraft.create(
            membership_id=uuid4(),
            skill_id=uuid4(),
            level=level,  # type: ignore[arg-type]
            verified_by_membership_id=uuid4(),
            evidence=(),
        )


def test_person_skill_rejects_missing_verifier() -> None:
    with pytest.raises(InvalidSkillFieldError) as error:
        PersonSkillDraft.create(
            membership_id=uuid4(),
            skill_id=uuid4(),
            level=3,
            verified_by_membership_id=None,
            evidence=(),
        )

    assert error.value.field == "verified_by_membership_id"


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"evidence_type": "MODEL_GUESS"}, "evidence_type"),
        ({"summary": "   "}, "summary"),
        ({"summary": "x" * 2001}, "summary"),
        ({"source_resource_type": "   "}, "source_resource_type"),
        ({"occurred_at": datetime(2026, 8, 25)}, "occurred_at"),
    ],
)
def test_skill_evidence_rejects_unsafe_or_incomplete_provenance(
    values: dict[str, object], field: str
) -> None:
    inputs: dict[str, object] = {
        "evidence_type": "MANAGER_NOTE",
        "summary": "Observed during review",
        "source_resource_type": "review",
        "source_resource_id": uuid4(),
        "occurred_at": datetime(2026, 8, 25, tzinfo=UTC),
    }
    inputs.update(values)

    with pytest.raises(InvalidEvidenceFieldError) as error:
        SkillEvidenceDraft.create(**inputs)  # type: ignore[arg-type]

    assert error.value.field == field


def test_person_skill_patch_requires_a_change_and_verifier() -> None:
    with pytest.raises(EmptyPersonSkillPatchError):
        PersonSkillPatch.create().validate_not_empty()

    with pytest.raises(InvalidSkillFieldError) as error:
        PersonSkillPatch.create(level=4)

    assert error.value.field == "verified_by_membership_id"

    patch = PersonSkillPatch.create(
        level=4,
        verified_by_membership_id=uuid4(),
        evidence=(),
    )
    assert patch.level is SkillLevel.LEVEL_4
    assert patch.level_supplied is True


def test_verified_person_skill_reverification_applies_patch_and_one_version() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    verifier_id = uuid4()
    person_skill = VerifiedPersonSkill(
        id=uuid4(),
        organization_id=uuid4(),
        membership_id=uuid4(),
        skill_id=uuid4(),
        level=SkillLevel.LEVEL_2,
        verified_by_membership_id=uuid4(),
        verified_at=now,
        version=4,
        created_at=now,
        updated_at=now,
    )
    verified_at = datetime(2026, 8, 26, 9, tzinfo=UTC)
    updated_at = datetime(2026, 8, 26, 10, tzinfo=UTC)

    updated = person_skill.apply(
        PersonSkillPatch.create(level=4, verified_by_membership_id=verifier_id),
        verified_at=verified_at,
        updated_at=updated_at,
    )

    assert updated.level is SkillLevel.LEVEL_4
    assert updated.verified_by_membership_id == verifier_id
    assert updated.verified_at == verified_at
    assert updated.version == 5
    assert updated.updated_at == updated_at
    assert updated.created_at == now


@pytest.mark.parametrize(
    ("verified_at", "updated_at", "field"),
    [
        (datetime(2026, 8, 26), datetime(2026, 8, 26, tzinfo=UTC), "verified_at"),
        (datetime(2026, 8, 26, tzinfo=UTC), datetime(2026, 8, 26), "updated_at"),
    ],
)
def test_verified_person_skill_reverification_rejects_naive_timestamps(
    verified_at: datetime, updated_at: datetime, field: str
) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    person_skill = VerifiedPersonSkill(
        id=uuid4(),
        organization_id=uuid4(),
        membership_id=uuid4(),
        skill_id=uuid4(),
        level=SkillLevel.LEVEL_2,
        verified_by_membership_id=uuid4(),
        verified_at=now,
        version=1,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(InvalidSkillFieldError) as error:
        person_skill.apply(
            PersonSkillPatch.create(level=3, verified_by_membership_id=uuid4()),
            verified_at=verified_at,
            updated_at=updated_at,
        )

    assert error.value.field == field


def test_work_outcome_evidence_retains_exact_completed_resource_provenance() -> None:
    task_id = uuid4()
    observed_at = datetime(2026, 8, 24, tzinfo=UTC)

    evidence = WorkOutcomeEvidenceDraft.create(
        evidence_type="COMPLETED_TASK",
        summary="  Approved deliverable completed  ",
        source_resource_type="Task",
        source_resource_id=task_id,
        source_resource_version=7,
        observed_at=observed_at,
    )

    assert evidence.evidence_type is SkillEvidenceType.COMPLETED_TASK
    assert evidence.summary == "Approved deliverable completed"
    assert evidence.source_resource_type == "task"
    assert evidence.source_resource_id == task_id
    assert evidence.source_resource_version == 7
    assert evidence.observed_at == observed_at


@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({"evidence_type": "CERTIFICATE"}, "evidence_type"),
        ({"source_resource_type": "document"}, "source_resource_type"),
        ({"source_resource_version": 0}, "source_resource_version"),
        ({"source_resource_version": True}, "source_resource_version"),
        ({"source_resource_version": 1.5}, "source_resource_version"),
        ({"observed_at": datetime(2026, 8, 25)}, "observed_at"),
    ],
)
def test_work_outcome_evidence_rejects_non_outcome_or_inexact_provenance(
    values: dict[str, object], field: str
) -> None:
    inputs: dict[str, object] = {
        "evidence_type": "REVIEW_OUTCOME",
        "summary": "Strong review outcome",
        "source_resource_type": "review",
        "source_resource_id": uuid4(),
        "source_resource_version": 2,
        "observed_at": datetime(2026, 8, 25, tzinfo=UTC),
    }
    inputs.update(values)

    with pytest.raises(InvalidEvidenceFieldError) as error:
        WorkOutcomeEvidenceDraft.create(**inputs)  # type: ignore[arg-type]

    assert error.value.field == field
