"""Composition and translation boundary between backend and the AI package."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol, cast
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.core.config import Settings
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.planning_runs.application.job_service import JobHandler
from app.modules.planning_runs.application.ports import PlanningRunTransaction
from app.modules.planning_runs.domain.models import (
    ApprovalStatus,
    ModelInvocation,
    Proposal,
    ProposalStatus,
    ProposalVersion,
    UnsupportedPlanningCapabilityError,
    WorkflowCheckpoint,
    WorkflowEvent,
    WorkflowJob,
    WorkflowRun,
    WorkflowRunStatus,
)
from work_management_ai.model_gateway.contracts import (
    ModelGateway,
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


def build_model_gateway(settings: Settings) -> ModelGateway:
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


class CurrentActorResolver(Protocol):
    async def resolve(
        self, *, organization_id: UUID, membership_id: UUID
    ) -> AuthenticatedActor | None: ...


type PlanningTransactionFactory = Callable[[AuthenticatedActor | UUID], PlanningRunTransaction]


class WorkflowRecordingModelGateway:
    """Record allowlisted invocation metadata after a transaction-free model call."""

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        transaction_factory: PlanningTransactionFactory,
        organization_id: UUID,
        workflow_run_id: UUID,
    ) -> None:
        self._gateway = gateway
        self._transactions = transaction_factory
        self._organization_id = organization_id
        self._run_id = workflow_run_id

    async def generate_structured[StructuredOutputT: BaseModel](
        self, request: StructuredModelRequest[StructuredOutputT]
    ) -> StructuredModelResponse[StructuredOutputT]:
        started = monotonic()
        status = "SUCCESS"
        model_ref = "unavailable"
        try:
            response = await self._gateway.generate_structured(request)
            model_ref = response.model_ref
        except Exception:
            status = "FAILED"
            model_ref = "unavailable"
            raise
        finally:
            provider, _, model_name = model_ref.partition(":")
            async with self._transactions(self._organization_id) as transaction:
                await transaction.repository.record_model_invocation(
                    invocation=ModelInvocation(
                        id=uuid4(),
                        organization_id=self._organization_id,
                        workflow_run_id=self._run_id,
                        provider=provider or "unknown",
                        model_name=model_name or model_ref,
                        prompt_version=request.invocation_key,
                        schema_version=PLANNING_SCHEMA_VERSION,
                        invocation_key=request.invocation_key,
                        duration_ms=max(0, int((monotonic() - started) * 1000)),
                        status=status,
                    )
                )
                await transaction.commit()
        return response


class _PlanningContextAdapter:
    def __init__(self, transaction_factory: PlanningTransactionFactory, run: WorkflowRun) -> None:
        self._transactions = transaction_factory
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
        async with self._transactions(request.organization_id) as transaction:
            active = await transaction.repository.list_active_membership_ids(
                organization_id=request.organization_id
            )
            await transaction.commit()
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
    def __init__(
        self, transaction_factory: PlanningTransactionFactory, actor: AuthenticatedActor
    ) -> None:
        self._transactions = transaction_factory
        self._actor = actor

    async def save_checkpoint(self, checkpoint: PlanningCheckpoint) -> None:
        async with self._transactions(self._actor) as transaction:
            latest = await transaction.repository.get_latest_checkpoint(
                actor=self._actor, run_id=checkpoint.run_id
            )
            state = {**checkpoint.state, "_persistence_key": checkpoint.idempotency_key}
            if latest is None or latest.state.get("_persistence_key") != checkpoint.idempotency_key:
                await transaction.repository.save_checkpoint(
                    checkpoint=WorkflowCheckpoint(
                        id=uuid4(),
                        organization_id=checkpoint.organization_id,
                        workflow_run_id=checkpoint.run_id,
                        node=checkpoint.node,
                        sequence=1 if latest is None else latest.sequence + 1,
                        state=state,
                    )
                )
            await transaction.commit()

    async def append_progress(self, event: PlanningProgressEvent) -> None:
        payload = {**event.public_payload, "stage": event.stage}
        async with self._transactions(self._actor) as transaction:
            existing = await transaction.repository.list_events(
                actor=self._actor, run_id=event.run_id
            )
            event_type = f"workflow.{event.stage.casefold()}"
            if not (
                existing
                and existing[-1].event_type == event_type
                and existing[-1].public_payload == payload
            ):
                await transaction.repository.append_event(
                    event=WorkflowEvent(
                        id=uuid4(),
                        organization_id=event.organization_id,
                        workflow_run_id=event.run_id,
                        sequence=0,
                        event_type=event_type,
                        public_payload=payload,
                    )
                )
            await transaction.commit()

    async def persist_proposal(self, draft: PlanningProposalDraft) -> PersistedProposalReference:
        async with self._transactions(self._actor) as transaction:
            existing = await transaction.repository.get_proposal_by_run_id(
                actor=self._actor, run_id=draft.run_id
            )
            if existing is not None:
                await transaction.commit()
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
            await transaction.repository.create_proposal(proposal=proposal, initial_version=version)
            ready_proposal = await transaction.repository.complete_proposal_revalidation(
                actor=self._actor,
                proposal_id=proposal.id,
                version_number=1,
                validation_result=validation,
                request_id=f"workflow-run:{draft.run_id}",
            )
            await transaction.commit()
            return PersistedProposalReference(
                proposal_id=ready_proposal.id,
                version=ready_proposal.current_version_number,
            )


class PlanningJobHandler:
    """Execute only bounded Task 7 start/resume instructions."""

    def __init__(
        self,
        settings: Settings,
        transaction_factory: PlanningTransactionFactory,
        actor_resolver: CurrentActorResolver,
    ) -> None:
        self._settings = settings
        self._transactions = transaction_factory
        self._actors = actor_resolver

    async def __call__(self, *, job: WorkflowJob, worker_id: str) -> None:
        del worker_id
        async with self._transactions(job.organization_id) as transaction:
            run = await transaction.repository.get_workflow_run_by_scope(
                organization_id=job.organization_id,
                run_id=job.workflow_run_id,
            )
            await transaction.commit()
        if run is None:
            raise RuntimeError("WORKFLOW_RUN_UNAVAILABLE")
        actor = await self._actors.resolve(
            organization_id=run.organization_id,
            membership_id=run.requested_by_membership_id,
        )
        if actor is None:
            raise RuntimeError("ACTOR_CONTEXT_UNAVAILABLE")
        gateway = WorkflowRecordingModelGateway(
            gateway=build_model_gateway(self._settings),
            transaction_factory=self._transactions,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
        )
        graph = PlanningGraph(
            model_gateway=gateway,
            context_port=_PlanningContextAdapter(self._transactions, run),
            persistence_port=_PlanningPersistenceAdapter(self._transactions, actor),
        )
        result: PlanningGraphResult
        if job.job_type == "planning.start":
            if run.status is WorkflowRunStatus.QUEUED:
                async with self._transactions(actor) as transaction:
                    run = await transaction.repository.update_workflow_run(
                        actor=actor, run=run.mark_running()
                    )
                    await transaction.commit()
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
            async with self._transactions(actor) as transaction:
                checkpoint = await transaction.repository.get_latest_checkpoint(
                    actor=actor, run_id=run.id
                )
                await transaction.commit()
            if checkpoint is None or checkpoint.node != "await_manager_input":
                raise RuntimeError("manager-input checkpoint is unavailable")
            result = await graph.resume_from_checkpoint(
                checkpoint.state,
                str(job.payload.get("manager_message", "")),
            )
        else:
            raise RuntimeError("unsupported planning job type")
        await self._apply_result(actor, run, result)

    async def _apply_result(
        self,
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
        async with self._transactions(actor) as transaction:
            await transaction.repository.update_workflow_run(actor=actor, run=updated)
            await transaction.commit()


class ProposalRevalidationJobHandler:
    """Deterministically validate the edited immutable version without applying it."""

    def __init__(
        self,
        transaction_factory: PlanningTransactionFactory,
        actor_resolver: CurrentActorResolver,
    ) -> None:
        self._transactions = transaction_factory
        self._actors = actor_resolver

    async def __call__(self, *, job: WorkflowJob, worker_id: str) -> None:
        del worker_id
        proposal_id = UUID(str(job.payload.get("proposal_id", "")))
        version_number = int(job.payload.get("proposal_version", 0))
        async with self._transactions(job.organization_id) as transaction:
            run = await transaction.repository.get_workflow_run_by_scope(
                organization_id=job.organization_id,
                run_id=job.workflow_run_id,
            )
            creator_id = await transaction.repository.get_proposal_version_creator_by_scope(
                organization_id=job.organization_id,
                proposal_id=proposal_id,
                version_number=version_number,
            )
            await transaction.commit()
        if run is None:
            raise RuntimeError("WORKFLOW_RUN_UNAVAILABLE")
        if creator_id is None:
            raise RuntimeError("PROPOSAL_VERSION_UNAVAILABLE")
        actor = await self._actors.resolve(
            organization_id=job.organization_id, membership_id=creator_id
        )
        if actor is None:
            raise RuntimeError("ACTOR_CONTEXT_UNAVAILABLE")
        async with self._transactions(actor) as transaction:
            version = await transaction.repository.get_proposal_version(
                actor=actor,
                proposal_id=proposal_id,
                version_number=version_number,
            )
            if version is None:
                raise RuntimeError("PROPOSAL_VERSION_UNAVAILABLE")
            active = await transaction.repository.list_active_membership_ids(
                organization_id=job.organization_id
            )
            validation = verify_plan(
                PlanningModelOutput.model_validate(version.content),
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
            await transaction.commit()


class PlanningFinalizationJobHandler:
    """Finalize a committed Manager decision without invoking the model."""

    def __init__(
        self,
        transaction_factory: PlanningTransactionFactory,
        actor_resolver: CurrentActorResolver,
    ) -> None:
        self._transactions = transaction_factory
        self._actors = actor_resolver

    async def __call__(self, *, job: WorkflowJob, worker_id: str) -> None:
        del worker_id
        try:
            approval_id = UUID(str(job.payload["approval_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("FINALIZATION_PAYLOAD_INVALID") from error
        async with self._transactions(job.organization_id) as scope_transaction:
            run = await scope_transaction.repository.get_workflow_run_by_scope(
                organization_id=job.organization_id,
                run_id=job.workflow_run_id,
            )
            decider_id = await scope_transaction.repository.get_approval_decider_by_scope(
                organization_id=job.organization_id, approval_id=approval_id
            )
            await scope_transaction.commit()
        if run is None:
            raise RuntimeError("WORKFLOW_RUN_UNAVAILABLE")
        if run.status is WorkflowRunStatus.COMPLETED:
            return
        if run.status is not WorkflowRunStatus.WAITING_FOR_DECISION:
            raise RuntimeError("WORKFLOW_RUN_NOT_WAITING_FOR_DECISION")
        if decider_id is None:
            raise RuntimeError("APPROVAL_DECIDER_UNAVAILABLE")
        actor = await self._actors.resolve(
            organization_id=job.organization_id, membership_id=decider_id
        )
        if actor is None:
            raise RuntimeError("ACTOR_CONTEXT_UNAVAILABLE")
        try:
            proposal_id = UUID(str(job.payload["proposal_id"]))
            proposal_version = int(job.payload["proposal_version"])
            checkpoint_sequence = int(job.payload["checkpoint_sequence"])
            decision = str(job.payload["decision"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("FINALIZATION_PAYLOAD_INVALID") from error
        async with self._transactions(actor) as transaction:
            approval = await transaction.repository.get_approval(
                actor=actor,
                approval_id=approval_id,
            )
            proposal = await transaction.repository.get_proposal(
                actor=actor,
                proposal_id=proposal_id,
            )
            checkpoint = await transaction.repository.get_latest_checkpoint(
                actor=actor,
                run_id=run.id,
            )
            expected = {
                "APPROVE": (ApprovalStatus.APPROVED, ProposalStatus.APPROVED),
                "REJECT": (ApprovalStatus.REJECTED, ProposalStatus.REJECTED),
            }.get(decision)
            if (
                approval is None
                or proposal is None
                or expected is None
                or approval.status is not expected[0]
                or proposal.status is not expected[1]
                or approval.proposal_id != proposal.id
                or approval.proposal_version_number != proposal_version
                or proposal.current_version_number != proposal_version
                or proposal.workflow_run_id != run.id
                or checkpoint is None
                or checkpoint.node != "await_manager_decision"
                or checkpoint.sequence != checkpoint_sequence
            ):
                raise RuntimeError("COMMITTED_DECISION_MISMATCH")
            completed = run.mark_completed()
            await transaction.repository.update_workflow_run(actor=actor, run=completed)
            await transaction.repository.save_checkpoint(
                checkpoint=WorkflowCheckpoint(
                    id=uuid4(),
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    node="completed",
                    sequence=checkpoint.sequence + 1,
                    state={
                        "stage": "COMPLETED",
                        "decision": decision,
                        "proposal_id": str(proposal.id),
                        "proposal_version": proposal_version,
                        "approval_id": str(approval.id),
                    },
                )
            )
            await transaction.repository.append_event(
                event=WorkflowEvent(
                    id=uuid4(),
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    sequence=0,
                    event_type="workflow.completed",
                    public_payload={
                        "status": "COMPLETED",
                        "decision": decision,
                        "proposal_id": str(proposal.id),
                        "proposal_version": proposal_version,
                        "approval_id": str(approval.id),
                    },
                )
            )
            await transaction.commit()


def build_planning_job_handlers(
    settings: Settings,
    transaction_factory: PlanningTransactionFactory,
    actor_resolver: CurrentActorResolver,
) -> dict[str, JobHandler]:
    planning = PlanningJobHandler(settings, transaction_factory, actor_resolver)
    return {
        "planning.start": planning,
        "planning.resume": planning,
        "proposal.revalidate": ProposalRevalidationJobHandler(transaction_factory, actor_resolver),
        "planning.finalize": PlanningFinalizationJobHandler(transaction_factory, actor_resolver),
    }
