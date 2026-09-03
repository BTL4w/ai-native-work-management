"""Derive explicit, editable Project Team requirements from approved Tasks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid5

from app.modules.people_capacity.domain.skills import SkillLevel
from app.modules.work.domain.tasks import Task

_REQUIREMENT_NAMESPACE = UUID("65c10bd5-0994-4b3a-a8bf-07a698f3c151")


def canonical_skill_label(value: str) -> str:
    """Normalize a skill label using the established Task-domain rule."""

    return " ".join(value.lower().split())


@dataclass(frozen=True, slots=True)
class IncompleteRequirement:
    """A task fact that needs Manager completion before confirmation."""

    task_id: UUID
    task_title: str
    reason: str


@dataclass(frozen=True, slots=True)
class TeamRequirement:
    """One skill and week demand that can be confirmed or edited by a Manager."""

    id: UUID
    organization_id: UUID
    project_week_id: UUID
    skill_label: str
    minimum_level: SkillLevel
    required_effort_hours: Decimal
    task_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        normalized_label = canonical_skill_label(self.skill_label)
        if not normalized_label:
            raise ValueError("skill_label")
        if self.required_effort_hours <= Decimal("0"):
            raise ValueError("required_effort_hours")
        object.__setattr__(self, "skill_label", normalized_label)
        object.__setattr__(self, "task_ids", tuple(self.task_ids))


@dataclass(frozen=True, slots=True)
class RequirementDraft:
    """The complete deterministic requirement draft for a set of Tasks."""

    requirements: tuple[TeamRequirement, ...]
    incomplete_items: tuple[IncompleteRequirement, ...]
    confirmable: bool


def _requirement_id(
    *,
    organization_id: UUID,
    project_id: UUID,
    project_week_id: UUID,
    skill_label: str,
    minimum_level: SkillLevel,
) -> UUID:
    return uuid5(
        _REQUIREMENT_NAMESPACE,
        ":".join(
            (
                str(organization_id),
                str(project_id),
                str(project_week_id),
                skill_label,
                str(int(minimum_level)),
            )
        ),
    )


def derive_requirement_draft(*, tasks: Iterable[Task]) -> RequirementDraft:
    """Aggregate task skill demand without inventing missing task facts.

    Tasks currently carry skill labels but not required proficiency.  Each
    resolved label therefore starts at the explicit, editable LEVEL_1 baseline.
    """

    grouped: dict[tuple[UUID, UUID, UUID, str, SkillLevel], list[Task]] = {}
    incomplete: list[IncompleteRequirement] = []
    for task in tasks:
        missing_reasons: list[str] = []
        canonical_labels = tuple(
            dict.fromkeys(canonical_skill_label(label) for label in task.required_skill_labels)
        )
        if not canonical_labels or any(not label for label in canonical_labels):
            missing_reasons.append("REQUIRED_SKILL_MISSING")
        if task.estimated_effort_hours is None:
            missing_reasons.append("ESTIMATED_EFFORT_MISSING")
        if task.project_week_id is None:
            missing_reasons.append("PROJECT_WEEK_MISSING")
        if missing_reasons:
            incomplete.extend(
                IncompleteRequirement(task.id, task.title, reason) for reason in missing_reasons
            )
            continue
        assert task.project_week_id is not None
        for normalized_label in canonical_labels:
            key = (
                task.organization_id,
                task.project_id,
                task.project_week_id,
                normalized_label,
                SkillLevel.LEVEL_1,
            )
            grouped.setdefault(key, []).append(task)

    requirements = tuple(
        TeamRequirement(
            id=_requirement_id(
                organization_id=organization_id,
                project_id=project_id,
                project_week_id=project_week_id,
                skill_label=skill_label,
                minimum_level=minimum_level,
            ),
            organization_id=organization_id,
            project_week_id=project_week_id,
            skill_label=skill_label,
            minimum_level=minimum_level,
            required_effort_hours=Decimal(sum(task.estimated_effort_hours or 0 for task in values)),
            task_ids=tuple(sorted((task.id for task in values), key=str)),
        )
        for (
            organization_id,
            project_id,
            project_week_id,
            skill_label,
            minimum_level,
        ), values in sorted(
            grouped.items(),
            key=lambda item: (
                str(item[0][2]),
                item[0][3],
                str(
                    _requirement_id(
                        organization_id=item[0][0],
                        project_id=item[0][1],
                        project_week_id=item[0][2],
                        skill_label=item[0][3],
                        minimum_level=item[0][4],
                    )
                ),
            ),
        )
    )
    incomplete_items = tuple(sorted(incomplete, key=lambda item: (str(item.task_id), item.reason)))
    return RequirementDraft(
        requirements=requirements,
        incomplete_items=incomplete_items,
        confirmable=not incomplete_items,
    )
