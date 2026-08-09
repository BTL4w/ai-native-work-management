"""Typed contracts for applying one immutable planning proposal decision."""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.modules.planning_runs.domain.models import (
    ApprovalStatus,
    ProposalStatus,
)


class ApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class CreatedBusinessIds:
    project_id: UUID | None = None
    goal_id: UUID | None = None
    milestone_ids: tuple[UUID, ...] = field(default_factory=tuple)
    task_ids: tuple[UUID, ...] = field(default_factory=tuple)
    dependency_ids: tuple[UUID, ...] = field(default_factory=tuple)
    acceptance_criterion_ids: tuple[UUID, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ApprovalDecisionResult:
    approval_id: UUID
    approval_status: ApprovalStatus
    proposal_id: UUID
    proposal_version: int
    proposal_status: ProposalStatus
    workflow_run_id: UUID
    finalization_job_id: UUID
    created: CreatedBusinessIds = field(default_factory=CreatedBusinessIds)
    replayed: bool = False
