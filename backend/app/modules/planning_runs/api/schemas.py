"""Strict public schemas for asynchronous planning runs and proposals."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.planning_runs.application.ports import WorkflowRunSnapshot
from app.modules.planning_runs.domain.models import Proposal, ProposalVersion, WorkflowRun


class PlanningRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    locale: Literal["vi", "en"]

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class ManagerMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class ProposalEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, object]


class WorkflowRunReferenceResponse(BaseModel):
    run_id: UUID
    status: str
    version: int

    @classmethod
    def from_domain(cls, run: WorkflowRun) -> Self:
        return cls(run_id=run.id, status=run.status.value, version=run.version)


class WorkflowProposalSnapshotResponse(BaseModel):
    proposal_id: UUID
    status: str
    version: int
    validation_result: dict[str, object]
    content: dict[str, object]


class WorkflowTimelineItemResponse(BaseModel):
    sequence: int
    event_type: str
    payload: dict[str, object]
    occurred_at: datetime


def _timeline_items() -> list[WorkflowTimelineItemResponse]:
    return []


class WorkflowRunResponse(BaseModel):
    id: UUID
    project_id: UUID | None
    status: str
    workflow_name: str
    workflow_version: str
    verifier_version: str
    input_goal_text: str
    version: int
    created_at: datetime
    updated_at: datetime
    current_stage: str | None = None
    current_proposal: WorkflowProposalSnapshotResponse | None = None
    public_timeline: list[WorkflowTimelineItemResponse] = Field(default_factory=_timeline_items)
    allowed_actions: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, run: WorkflowRun) -> Self:
        return cls(
            id=run.id,
            project_id=run.project_id,
            status=run.status.value,
            workflow_name=run.workflow_name,
            workflow_version=run.workflow_version,
            verifier_version=run.verifier_version,
            input_goal_text=run.input_goal_text,
            version=run.version,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @classmethod
    def from_snapshot(cls, snapshot: WorkflowRunSnapshot) -> Self:
        response = cls.from_domain(snapshot.run)
        response.current_stage = (
            snapshot.checkpoint.node
            if snapshot.checkpoint is not None
            else snapshot.run.status.value
        )
        if snapshot.proposal is not None and snapshot.proposal_version is not None:
            response.current_proposal = WorkflowProposalSnapshotResponse(
                proposal_id=snapshot.proposal.id,
                status=snapshot.proposal.status.value,
                version=snapshot.proposal_version.version_number,
                validation_result=snapshot.proposal_version.validation_result,
                content=snapshot.proposal_version.content,
            )
        response.public_timeline = [
            WorkflowTimelineItemResponse(
                sequence=event.sequence,
                event_type=event.event_type,
                payload=event.public_payload,
                occurred_at=event.created_at,
            )
            for event in snapshot.events
        ]
        actions: list[str] = []
        if snapshot.run.status.value == "NEEDS_INPUT":
            actions.append("MESSAGE")
        if snapshot.proposal is not None and not snapshot.proposal.status.is_terminal:
            actions.append("EDIT_PROPOSAL")
        response.allowed_actions = actions
        return response


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunResponse]


class ProposalReferenceResponse(BaseModel):
    proposal_id: UUID
    workflow_run_id: UUID
    status: str
    version: int
    content: dict[str, object]

    @classmethod
    def from_domain(cls, proposal: Proposal, version: ProposalVersion) -> Self:
        return cls(
            proposal_id=proposal.id,
            workflow_run_id=proposal.workflow_run_id,
            status=proposal.status.value,
            version=version.version_number,
            content=version.content,
        )
