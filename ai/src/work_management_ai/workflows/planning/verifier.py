"""Deterministic verification for typed planning proposals."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from work_management_ai.schemas.planning import PlanningModelOutput

PLANNING_VERIFIER_VERSION = "2.0.0"
MAX_MILESTONES = 20
MAX_TASKS = 100
MAX_DEPENDENCIES = 200
MAX_ACCEPTANCE_CRITERIA_PER_TASK = 20


@dataclass(frozen=True, slots=True)
class PlanningVerificationContext:
    """Permitted facts used by deterministic verification."""

    # Intentionally empty: weekly planning must not load Employee context.


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

    del context
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
    if (
        plan.project.start_date is not None
        and plan.project.due_date is not None
        and plan.project.start_date > plan.project.due_date
    ):
        error("project.start_date", "PROJECT_DATE_ORDER")
    if (
        plan.goal.target_date is not None
        and plan.project.due_date is not None
        and plan.goal.target_date > plan.project.due_date
    ):
        error("goal.target_date", "GOAL_AFTER_PROJECT")

    milestone_by_ref = {milestone.ref: milestone for milestone in plan.milestones}
    week_by_ref = {week.ref: week for week in plan.project_weeks}
    task_by_ref = {task.ref: task for task in plan.tasks}
    if len(milestone_by_ref) != len(plan.milestones):
        error("milestones", "MILESTONE_REF_DUPLICATE")
    if len(task_by_ref) != len(plan.tasks):
        error("tasks", "TASK_REF_DUPLICATE")
    if len(week_by_ref) != len(plan.project_weeks):
        error("project_weeks", "PROJECT_WEEK_REF_DUPLICATE")

    ordered_weeks = sorted(plan.project_weeks, key=lambda week: week.week_number)
    if [week.week_number for week in ordered_weeks] != list(range(1, len(ordered_weeks) + 1)):
        error("project_weeks", "PROJECT_WEEK_NUMBER_SEQUENCE")
    for index, week in enumerate(ordered_weeks):
        path = f"project_weeks[{week.ref}]"
        if week.end_date < week.start_date:
            error(f"{path}.end_date", "PROJECT_WEEK_DATE_ORDER")
        if index and ordered_weeks[index - 1].end_date >= week.start_date:
            error(path, "PROJECT_WEEK_DATE_OVERLAP")
        if plan.project.start_date is not None and week.start_date < plan.project.start_date:
            error(f"{path}.start_date", "PROJECT_WEEK_OUTSIDE_PROJECT")
        if plan.project.due_date is not None and week.end_date > plan.project.due_date:
            error(f"{path}.end_date", "PROJECT_WEEK_OUTSIDE_PROJECT")

    for milestone in plan.milestones:
        if (
            milestone.due_date is not None
            and plan.project.due_date is not None
            and milestone.due_date > plan.project.due_date
        ):
            error(f"milestones[{milestone.ref}].due_date", "MILESTONE_AFTER_PROJECT")

    for task in plan.tasks:
        task_path = f"tasks[{task.ref}]"
        week = week_by_ref.get(task.project_week_ref)
        if week is None:
            error(f"{task_path}.project_week_ref", "PROJECT_WEEK_REF_OUTSIDE_CONTEXT")
        elif task.due_date is not None and not week.start_date <= task.due_date <= week.end_date:
            error(f"{task_path}.due_date", "TASK_OUTSIDE_PROJECT_WEEK")
        if not 1 <= task.estimated_effort_hours <= 10_000:
            error(f"{task_path}.estimated_effort_hours", "TASK_EFFORT_INVALID")
        normalized_skills = [label.strip().casefold() for label in task.required_skill_labels]
        if (
            len(normalized_skills) > 20
            or any(not label or len(label) > 80 for label in normalized_skills)
            or len(set(normalized_skills)) != len(normalized_skills)
        ):
            error(f"{task_path}.required_skill_labels", "TASK_SKILL_LABELS_INVALID")

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
