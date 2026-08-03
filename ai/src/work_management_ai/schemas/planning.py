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


class ProposedTask(PlanningSchema):
    ref: str
    milestone_ref: str | None
    title: str
    description: str | None
    due_date: date | None
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
    tasks: list[ProposedTask]
    dependencies: list[ProposedDependency]
    assumptions: list[ProposedAssumption]
