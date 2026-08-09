"""Deterministic verification for typed planning proposals."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from work_management_ai.schemas.planning import PlanningModelOutput

PLANNING_VERIFIER_VERSION = "1.0.0"
MAX_MILESTONES = 20
MAX_TASKS = 100
MAX_DEPENDENCIES = 200
MAX_ACCEPTANCE_CRITERIA_PER_TASK = 20


@dataclass(frozen=True, slots=True)
class PlanningVerificationContext:
    """Permitted facts used by deterministic verification."""

    active_membership_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class PlanningValidationItem:
    """One stable, localizable verifier finding."""

    path: str
    code: str
    message_key: str
    severity: Literal["ERROR", "WARNING"]


@dataclass(frozen=True, slots=True)
class PlanningValidationResult:
    """Ordered verifier findings and the derived approval eligibility."""

    errors: tuple[PlanningValidationItem, ...]
    warnings: tuple[PlanningValidationItem, ...]

    @property
    def can_approve(self) -> bool:
        return not self.errors


def verify_plan(
    plan: PlanningModelOutput,
    context: PlanningVerificationContext,
) -> PlanningValidationResult:
    """Verify business invariants without invoking a model."""

    errors: list[PlanningValidationItem] = []
    warnings: list[PlanningValidationItem] = []

    def error(path: str, code: str) -> None:
        errors.append(
            PlanningValidationItem(
                path=path,
                code=code,
                message_key=f"planning.validation.{_lower_camel(code)}",
                severity="ERROR",
            )
        )

    def warning(path: str, code: str) -> None:
        warnings.append(
            PlanningValidationItem(
                path=path,
                code=code,
                message_key=f"planning.validation.{_lower_camel(code)}",
                severity="WARNING",
            )
        )

    if len(plan.milestones) > MAX_MILESTONES:
        error("milestones", "MILESTONE_LIMIT_EXCEEDED")
    if len(plan.tasks) > MAX_TASKS:
        error("tasks", "TASK_LIMIT_EXCEEDED")
    if len(plan.dependencies) > MAX_DEPENDENCIES:
        error("dependencies", "DEPENDENCY_LIMIT_EXCEEDED")

    milestone_by_ref = {milestone.ref: milestone for milestone in plan.milestones}
    task_by_ref = {task.ref: task for task in plan.tasks}
    if len(milestone_by_ref) != len(plan.milestones):
        error("milestones", "MILESTONE_REF_DUPLICATE")
    if len(task_by_ref) != len(plan.tasks):
        error("tasks", "TASK_REF_DUPLICATE")

    for milestone in plan.milestones:
        if (
            milestone.due_date is not None
            and plan.project.due_date is not None
            and milestone.due_date > plan.project.due_date
        ):
            error(f"milestones[{milestone.ref}].due_date", "MILESTONE_AFTER_PROJECT")

    for task in plan.tasks:
        task_path = f"tasks[{task.ref}]"
        if task.assignee_membership_id is None:
            error(f"{task_path}.assignee_membership_id", "ASSIGNEE_REQUIRED")
        elif task.assignee_membership_id not in context.active_membership_ids:
            error(f"{task_path}.assignee_membership_id", "ASSIGNEE_NOT_PERMITTED")

        milestone = (
            milestone_by_ref.get(task.milestone_ref) if task.milestone_ref is not None else None
        )
        if task.milestone_ref is not None and milestone is None:
            error(f"{task_path}.milestone_ref", "MILESTONE_REF_OUTSIDE_CONTEXT")
        elif (
            milestone is not None
            and task.due_date is not None
            and milestone.due_date is not None
            and task.due_date > milestone.due_date
        ):
            error(f"{task_path}.due_date", "TASK_AFTER_MILESTONE")

        if len(task.acceptance_criteria) > MAX_ACCEPTANCE_CRITERIA_PER_TASK:
            error(
                f"{task_path}.acceptance_criteria",
                "ACCEPTANCE_CRITERIA_LIMIT_EXCEEDED",
            )
        if not task.acceptance_criteria:
            warning(f"{task_path}.acceptance_criteria", "ACCEPTANCE_CRITERIA_MISSING")
        normalized_criteria: set[str] = set()
        for index, criterion in enumerate(task.acceptance_criteria):
            normalized = " ".join(criterion.split()).casefold()
            if normalized in normalized_criteria:
                error(
                    f"{task_path}.acceptance_criteria[{index}]",
                    "ACCEPTANCE_CRITERION_DUPLICATE",
                )
            normalized_criteria.add(normalized)

    valid_edges: list[tuple[str, str]] = []
    edge_set: set[tuple[str, str]] = set()
    for index, dependency in enumerate(plan.dependencies):
        dependency_path = f"dependencies[{index}]"
        predecessor_exists = dependency.predecessor_ref in task_by_ref
        successor_exists = dependency.successor_ref in task_by_ref
        if not predecessor_exists:
            error(f"{dependency_path}.predecessor_ref", "TASK_REF_OUTSIDE_CONTEXT")
        if not successor_exists:
            error(f"{dependency_path}.successor_ref", "TASK_REF_OUTSIDE_CONTEXT")
        edge = (dependency.predecessor_ref, dependency.successor_ref)
        if dependency.predecessor_ref == dependency.successor_ref:
            error(dependency_path, "DEPENDENCY_SELF_EDGE")
        elif edge in edge_set:
            error(dependency_path, "DEPENDENCY_DUPLICATE")
        elif predecessor_exists and successor_exists:
            edge_set.add(edge)
            valid_edges.append(edge)

    if _contains_cycle(task_by_ref, valid_edges):
        error("dependencies", "DEPENDENCY_CYCLE")

    return PlanningValidationResult(
        errors=tuple(sorted(errors, key=lambda item: (item.path, item.code))),
        warnings=tuple(sorted(warnings, key=lambda item: (item.path, item.code))),
    )


def _contains_cycle(
    tasks: Mapping[str, object],
    edges: list[tuple[str, str]],
) -> bool:
    adjacency: dict[str, list[str]] = {task_ref: [] for task_ref in tasks}
    in_degree = dict.fromkeys(tasks, 0)
    for predecessor, successor in edges:
        adjacency[predecessor].append(successor)
        in_degree[successor] += 1
    ready = [task_ref for task_ref, degree in in_degree.items() if degree == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for successor in adjacency[current]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                ready.append(successor)
    return visited != len(tasks)


def _lower_camel(code: str) -> str:
    words = code.casefold().split("_")
    return words[0] + "".join(word.title() for word in words[1:])
