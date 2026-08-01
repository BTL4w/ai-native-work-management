"""Project domain rules independent of FastAPI and persistence."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.work.domain.projects import (
    EmptyProjectPatchError,
    InvalidProjectFieldError,
    Project,
    ProjectDraft,
    ProjectPatch,
)


def test_project_draft_normalizes_business_text() -> None:
    draft = ProjectDraft.create(name="  Customer onboarding  ", description="  Playbook  ")

    assert draft == ProjectDraft(name="Customer onboarding", description="Playbook")
    assert ProjectDraft.create(name="Roadmap", description="   ").description is None


@pytest.mark.parametrize("name", ["", "   ", "x" * 161])
def test_project_draft_rejects_invalid_name(name: str) -> None:
    with pytest.raises(InvalidProjectFieldError) as error:
        ProjectDraft.create(name=name, description=None)

    assert error.value.field == "name"


def test_project_draft_rejects_oversized_description() -> None:
    with pytest.raises(InvalidProjectFieldError) as error:
        ProjectDraft.create(name="Roadmap", description="x" * 5001)

    assert error.value.field == "description"


def test_project_patch_distinguishes_omitted_and_explicit_null_description() -> None:
    untouched = ProjectPatch.create()
    cleared = ProjectPatch.create(description=None, description_supplied=True)

    with pytest.raises(EmptyProjectPatchError):
        untouched.validate_not_empty()
    assert cleared.description is None
    assert cleared.description_supplied is True


def test_project_patch_applies_one_version_increment() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    project = Project(
        id=uuid4(),
        organization_id=uuid4(),
        name="Before",
        description="Description",
        version=3,
        created_at=now,
        updated_at=now,
    )

    updated = project.apply(
        ProjectPatch.create(name="  After  ", description=None, description_supplied=True),
        updated_at=now,
    )

    assert updated.name == "After"
    assert updated.description is None
    assert updated.version == 4
