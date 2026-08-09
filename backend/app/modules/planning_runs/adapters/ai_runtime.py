"""Composition and translation boundary between backend and the AI package."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.core.config import Settings
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.application.job_service import JobHandler
from app.modules.planning_runs.application.ports import PlanningRunTransaction
from app.modules.planning_runs.domain.models import (
    Proposal,
    ProposalVersion,
    UnsupportedPlanningCapabilityError,
    WorkflowCheckpoint,
    WorkflowEvent,
    WorkflowJob,
    WorkflowRun,
    WorkflowRunStatus,
)
from work_management_ai.model_gateway.contracts import (
    StructuredModelRequest,
    StructuredModelResponse,
)
from work_management_ai.model_gateway.errors import ModelUnavailableError
from work_management_ai.model_gateway.mock import MockModelGateway
from work_management_ai.model_gateway.openai import OpenAIModelGateway
from work_management_ai.schemas.planning import PlanningModelOutput
from work_management_ai.workflows.planning.context import (
    PermittedPlanningContext,
    PlanningContextRequest,
)
from work_management_ai.workflows.planning.graph import PlanningGraph, PlanningGraphResult
from work_management_ai.workflows.planning.policy import evaluate_planning_policy
from work_management_ai.workflows.planning.ports import (
    PersistedProposalReference,
    PlanningCheckpoint,
    PlanningProgressEvent,
    PlanningProposalDraft,
)
from work_management_ai.workflows.planning.state import (
    PLANNING_SCHEMA_VERSION,
    PLANNING_WORKFLOW_VERSION,
    PlanningLocale,
    create_planning_state,
)
from work_management_ai.workflows.planning.verifier import (
    PLANNING_VERIFIER_VERSION,
    PlanningValidationItem,
    PlanningValidationResult,
    PlanningVerificationContext,
    verify_plan,
)


def _validation_json(validation: PlanningValidationResult) -> dict[str, object]:
    def item_json(finding: PlanningValidationItem) -> dict[str, object]:
        return {
            "path": finding.path,
            "code": finding.code,
            "message_key": finding.message_key,
            "severity": finding.severity,
        }

    return {
        "is_valid": validation.can_approve,
        "can_approve": validation.can_approve,
        "errors": [item_json(item) for item in validation.errors],
        "warnings": [item_json(item) for item in validation.warnings],
    }


class PlanningAIRuntime:
    """Expose deterministic Task 7 runtime metadata and validation to backend."""

    workflow_version = PLANNING_WORKFLOW_VERSION
    verifier_version = PLANNING_VERIFIER_VERSION
    schema_version = PLANNING_SCHEMA_VERSION

    def validate_capability(self, message: str) -> None:
        decision = evaluate_planning_policy(actor_role="MANAGER", user_brief=message)
        if decision.outcome != "ALLOW":
            raise UnsupportedPlanningCapabilityError

    def validate_proposal_content(self, content: dict[str, object]) -> dict[str, object]:
        validated = PlanningModelOutput.model_validate(content)
        return cast(dict[str, object], validated.model_dump(mode="python"))

    def validate_proposal_deterministically(
        self,
        content: dict[str, object],
        *,
        active_membership_ids: frozenset[UUID],
    ) -> dict[str, object]:
        validated = PlanningModelOutput.model_validate(content)
        result = verify_plan(
            validated,
            PlanningVerificationContext(
                active_membership_ids=active_membership_ids,
            ),
        )
        return _validation_json(result)


class _DisabledModelGateway:
    async def generate_structured[StructuredOutputT: BaseModel](
        self, request: StructuredModelRequest[StructuredOutputT]
    ) -> StructuredModelResponse[StructuredOutputT]:
        del request
        raise ModelUnavailableError("model provider is disabled")


def _mock_plan() -> dict[str, object]:
    return {
        "project": {
            "title": "Proposed project",
            "description": None,
            "start_date": None,
            "due_date": None,
        },
        "goal": {
            "title": "Proposed goal",
            "description": None,
            "expected_outcomes": ["Manager-reviewed outcome"],
            "target_date": None,
        },
        "milestones": [],
        "tasks": [],
        "dependencies": [],
        "assumptions": [],
    }


def _model_gateway(settings: Settings):
    if settings.ai_provider == "openai" and settings.openai_api_key is not None:
        return OpenAIModelGateway(
            model_name=settings.ai_model,
            api_key=settings.openai_api_key,
        )
    if settings.ai_provider == "mock":
        fixture = _mock_plan()
        return MockModelGateway(
            fixtures={
                f"planning.{locale}.{mode}": fixture
                for locale in ("vi", "en")
                for mode in ("generate", "repair", "revision")
            }
        )
    return _DisabledModelGateway()


def _worker_actor(run: WorkflowRun, role: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=UUID(int=0),
        email="workflow-worker@internal.invalid",
        display_name="Workflow worker",
        membership_id=run.requested_by_membership_id,
        organization_id=run.organization_id,
        organization_name="Tenant",
        role=MembershipRole(role),
    )


class _PlanningContextAdapter:
    def __init__(self, transaction: PlanningRunTransaction, run: WorkflowRun) -> None:
        self._transaction = transaction
        self._run = run

    async def load_permitted_context(
        self, request: PlanningContextRequest
    ) -> PermittedPlanningContext:
        if (
            request.organization_id != self._run.organization_id
            or request.run_id != self._run.id
            or request.actor_membership_id != self._run.requested_by_membership_id
        ):
            raise PermissionError("planning context scope mismatch")
        active = await self._transaction.repository.list_active_membership_ids(
            organization_id=request.organization_id
        )
        questions: tuple[str, ...] = ()
        if len(request.user_brief.split()) < 4 and not request.manager_answers:
            questions = ("Please provide more planning detail.",)
        return PermittedPlanningContext(
            reference_ids=(),
            active_membership_ids=active,
            required_questions=questions,
            structured_facts={},
        )


class _PlanningPersistenceAdapter:
    def __init__(self, transaction: PlanningRunTransaction, actor: AuthenticatedActor) -> None:
        self._transaction = transaction
        self._actor = actor

    async def save_checkpoint(self, checkpoint: PlanningCheckpoint) -> None:
        latest = await self._transaction.repository.get_latest_checkpoint(
            actor=self._actor, run_id=checkpoint.run_id
        )
        state = {**checkpoint.state, "_persistence_key": checkpoint.idempotency_key}
        if (
            latest is not None
            and latest.state.get("_persistence_key") == checkpoint.idempotency_key
        ):
            return
        await self._transaction.repository.save_checkpoint(
            checkpoint=WorkflowCheckpoint(
                id=uuid4(),
                organization_id=checkpoint.organization_id,
                workflow_run_id=checkpoint.run_id,
                node=checkpoint.node,
                sequence=1 if latest is None else latest.sequence + 1,
                state=state,
            )
        )

    async def append_progress(self, event: PlanningProgressEvent) -> None:
        payload = {**event.public_payload, "stage": event.stage}
        existing = await self._transaction.repository.list_events(
            actor=self._actor, run_id=event.run_id
        )
        event_type = f"workflow.{event.stage.casefold()}"
        if (
            existing
            and existing[-1].event_type == event_type
            and existing[-1].public_payload == payload
        ):
            return
        await self._transaction.repository.append_event(
            event=WorkflowEvent(
                id=uuid4(),
                organization_id=event.organization_id,
                workflow_run_id=event.run_id,
                sequence=0,
                event_type=event_type,
                public_payload=payload,
            )
        )

    async def persist_proposal(self, draft: PlanningProposalDraft) -> PersistedProposalReference:
        existing = await self._transaction.repository.get_proposal_by_run_id(
            actor=self._actor, run_id=draft.run_id
        )
        if existing is not None:
            return PersistedProposalReference(
                proposal_id=existing.id,
                version=existing.current_version_number,
            )
        proposal = Proposal.create(
            organization_id=draft.organization_id,
            workflow_run_id=draft.run_id,
        )
        validation = _validation_json(draft.validation)
        version = ProposalVersion(
            id=uuid4(),
            organization_id=draft.organization_id,
            proposal_id=proposal.id,
            version_number=1,
            created_by_membership_id=draft.actor_membership_id,
            content=cast(dict[str, object], draft.content.model_dump(mode="json")),
            assumptions=[item.model_dump(mode="json") for item in draft.content.assumptions],
            field_provenance={"default": "AI_PROPOSED"},
            validation_result=validation,
            source_reference_snapshot=[
                {"reference_id": value} for value in draft.context_reference_ids
            ],
            workflow_version=draft.workflow_version,
            prompt_version=draft.prompt_version,
            schema_version=draft.schema_version,
            model_reference=draft.model_reference,
            verifier_version=draft.verifier_version,
            creator_type="AI_SYSTEM",
        )
        await self._transaction.repository.create_proposal(
            proposal=proposal, initial_version=version
        )
        ready_proposal = await self._transaction.repository.complete_proposal_revalidation(
            actor=self._actor,
            proposal_id=proposal.id,
            version_number=1,
            validation_result=validation,
            request_id=f"workflow-run:{draft.run_id}",
        )
        return PersistedProposalReference(
            proposal_id=ready_proposal.id,
            version=ready_proposal.current_version_number,
        )


class PlanningJobHandler:
    """Execute only bounded Task 7 start/resume instructions."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(self, transaction: PlanningRunTransaction, job: WorkflowJob) -> None:
        run = await transaction.repository.get_workflow_run_by_scope(
            organization_id=job.organization_id,
            run_id=job.workflow_run_id,
        )
        if run is None:
            raise RuntimeError("workflow run is unavailable")
        actor = _worker_actor(run, str(job.payload.get("actor_role", MembershipRole.MANAGER.value)))
        graph = PlanningGraph(
            model_gateway=_model_gateway(self._settings),
            context_port=_PlanningContextAdapter(transaction, run),
            persistence_port=_PlanningPersistenceAdapter(transaction, actor),
        )
        result: PlanningGraphResult
        if job.job_type == "planning.start":
            if run.status is WorkflowRunStatus.QUEUED:
                run = await transaction.repository.update_workflow_run(
                    actor=actor, run=run.mark_running()
                )
            result = await graph.run(
                create_planning_state(
                    run_id=run.id,
                    organization_id=run.organization_id,
                    actor_membership_id=run.requested_by_membership_id,
                    actor_role=actor.role.value,
                    locale=cast(PlanningLocale, str(job.payload.get("locale", "en"))),
                    user_brief=run.input_goal_text,
                )
            )
        elif job.job_type == "planning.resume":
            checkpoint = await transaction.repository.get_latest_checkpoint(
                actor=actor, run_id=run.id
            )
            if checkpoint is None or checkpoint.node != "await_manager_input":
                raise RuntimeError("manager-input checkpoint is unavailable")
            result = await graph.resume_from_checkpoint(
                checkpoint.state,
                str(job.payload.get("manager_message", "")),
            )
        else:
            raise RuntimeError("unsupported planning job type")
        await self._apply_result(transaction, actor, run, result)

    @staticmethod
    async def _apply_result(
        transaction: PlanningRunTransaction,
        actor: AuthenticatedActor,
        run: WorkflowRun,
        result: PlanningGraphResult,
    ) -> None:
        if result.interrupt is not None and result.interrupt.kind == "MANAGER_INPUT_REQUIRED":
            updated = run.mark_needs_input()
        elif result.interrupt is not None and result.interrupt.kind == "MANAGER_DECISION_REQUIRED":
            updated = run.mark_waiting_for_decision()
        elif result.state["stage"] in {"MANUAL_FALLBACK", "UNSUPPORTED", "FORBIDDEN"}:
            updated = run.mark_failed("AI_WORKFLOW_UNAVAILABLE")
        else:
            return
        await transaction.repository.update_workflow_run(actor=actor, run=updated)


class ProposalRevalidationJobHandler:
    """Deterministically validate the edited immutable version without applying it."""

    async def __call__(self, transaction: PlanningRunTransaction, job: WorkflowJob) -> None:
        run = await transaction.repository.get_workflow_run_by_scope(
            organization_id=job.organization_id,
            run_id=job.workflow_run_id,
        )
        if run is None:
            raise RuntimeError("workflow run is unavailable")
        actor = _worker_actor(run, MembershipRole.MANAGER.value)
        proposal_id = UUID(str(job.payload.get("proposal_id", "")))
        version_number = int(job.payload.get("proposal_version", 0))
        version = await transaction.repository.get_proposal_version(
            actor=actor,
            proposal_id=proposal_id,
            version_number=version_number,
        )
        if version is None:
            raise RuntimeError("proposal version is unavailable")
        content = PlanningModelOutput.model_validate(version.content)
        active = await transaction.repository.list_active_membership_ids(
            organization_id=job.organization_id
        )
        validation = verify_plan(
            content,
            PlanningVerificationContext(active_membership_ids=active),
        )
        public_validation = _validation_json(validation)
        await transaction.repository.append_event(
            event=WorkflowEvent(
                id=uuid4(),
                organization_id=job.organization_id,
                workflow_run_id=job.workflow_run_id,
                sequence=0,
                event_type="proposal.validating",
                public_payload={
                    "proposal_id": str(job.payload.get("proposal_id", "")),
                    "version": int(job.payload.get("proposal_version", 0)),
                },
                created_at=datetime.now(UTC),
            )
        )
        proposal = await transaction.repository.complete_proposal_revalidation(
            actor=actor,
            proposal_id=proposal_id,
            version_number=version_number,
            validation_result=public_validation,
            request_id=f"workflow-job:{job.id}",
        )
        await transaction.repository.append_event(
            event=WorkflowEvent(
                id=uuid4(),
                organization_id=job.organization_id,
                workflow_run_id=job.workflow_run_id,
                sequence=0,
                event_type=(
                    "proposal.ready"
                    if proposal.status.value == "READY_FOR_DECISION"
                    else "proposal.validation_failed"
                ),
                public_payload={
                    "proposal_id": str(proposal_id),
                    "version": version_number,
                    "can_approve": validation.can_approve,
                    "error_codes": [item.code for item in validation.errors],
                },
            )
        )


def build_planning_job_handlers(settings: Settings) -> dict[str, JobHandler]:
    planning = PlanningJobHandler(settings)
    return {
        "planning.start": planning,
        "planning.resume": planning,
        "proposal.revalidate": ProposalRevalidationJobHandler(),
    }
