"""Typed structured output for the Phase 2 planning model."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class PlanningSchema(BaseModel):
    """Reject provider fields that are not part of the approved contract."""

    model_config = ConfigDict(extra="forbid")


class ProposedProject(PlanningSchema):
    """Project proposal; backend approval maps ``title`` to the Project name."""

    title: str
    description: str | None
    start_date: date | None
    due_date: date | None


class ProposedGoal(PlanningSchema):
    title: str
    description: str | None
    expected_outcomes: list[str]
    target_date: date | None


class ProposedMilestone(PlanningSchema):
    """Milestone proposal; list order determines position during approval mapping."""

    ref: str
    title: str
    description: str | None
    due_date: date | None


class ProposedProjectWeek(PlanningSchema):
    ref: str
    week_number: int
    start_date: date
    end_date: date
    objective: str


class ProposedTask(PlanningSchema):
    ref: str
    project_week_ref: str
    milestone_ref: str | None
    title: str
    description: str | None
    due_date: date | None
    assignee_membership_id: None = None
    required_skill_labels: list[str]
    estimated_effort_hours: int
    acceptance_criteria: list[str]


class ProposedDependency(PlanningSchema):
    predecessor_ref: str
    successor_ref: str


class ProposedAssumption(PlanningSchema):
    description: str
    source: str


class PlanningModelOutput(PlanningSchema):
    project: ProposedProject
    goal: ProposedGoal
    milestones: list[ProposedMilestone]
    project_weeks: list[ProposedProjectWeek]
    tasks: list[ProposedTask]
    dependencies: list[ProposedDependency]
    assumptions: list[ProposedAssumption]
