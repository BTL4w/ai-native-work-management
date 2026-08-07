"""PostgreSQL repository adapter for AI planning runs persistence."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.adapters.database_models import (
    ApprovalModel,
    ContextReferenceModel,
    ModelInvocationModel,
    OutboxEventModel,
    ProposalModel,
    ProposalVersionModel,
    WorkflowCheckpointModel,
    WorkflowEventModel,
    WorkflowJobModel,
    WorkflowRunModel,
)
from app.modules.planning_runs.application.ports import PlanningRunRepository
from app.modules.planning_runs.domain.models import (
    Approval,
    ApprovalStatus,
    ContextReference,
    InvalidTransitionError,
    ModelInvocation,
    OutboxEvent,
    OutboxStatus,
    PlanningRunDomainError,
    Proposal,
    ProposalStatus,
    ProposalVersion,
    WorkflowCheckpoint,
    WorkflowEvent,
    WorkflowJob,
    WorkflowJobStatus,
    WorkflowRun,
    WorkflowRunStatus,
)


class PostgreSQLPlanningRunRepository(PlanningRunRepository):
    """PostgreSQL implementation of PlanningRunRepository with RLS and tenant scoping."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_workflow_run(
        self,
        *,
        run: WorkflowRun,
        job: WorkflowJob | None = None,
    ) -> WorkflowRun:
        run_model = WorkflowRunModel(
            id=run.id,
            organization_id=run.organization_id,
            project_id=run.project_id,
            requested_by_membership_id=run.requested_by_membership_id,
            status=run.status.value,
            workflow_name=run.workflow_name,
            workflow_version=run.workflow_version,
            verifier_version=run.verifier_version,
            input_goal_text=run.input_goal_text,
            error_message=run.error_message,
            version=run.version,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
        self._session.add(run_model)
        await self._session.flush()

        if job is not None:
            job_model = WorkflowJobModel(
                id=job.id,
                organization_id=job.organization_id,
                workflow_run_id=job.workflow_run_id,
                job_type=job.job_type,
                status=job.status.value,
                payload=job.payload,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                available_at=job.available_at,
                locked_by_worker_id=job.locked_by_worker_id,
                lease_until=job.lease_until,
                last_error=job.last_error,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            self._session.add(job_model)
            await self._session.flush()
        return run

    async def get_workflow_run(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> WorkflowRun | None:
        stmt = select(WorkflowRunModel).where(
            WorkflowRunModel.id == run_id,
            WorkflowRunModel.organization_id == actor.organization_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return WorkflowRun(
            id=model.id,
            organization_id=model.organization_id,
            project_id=model.project_id,
            requested_by_membership_id=model.requested_by_membership_id,
            status=WorkflowRunStatus(model.status),
            workflow_name=model.workflow_name,
            workflow_version=model.workflow_version,
            verifier_version=model.verifier_version,
            input_goal_text=model.input_goal_text,
            error_message=model.error_message,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def update_workflow_run(
        self,
        *,
        actor: AuthenticatedActor,
        run: WorkflowRun,
    ) -> WorkflowRun:
        stmt = (
            update(WorkflowRunModel)
            .where(
                WorkflowRunModel.id == run.id,
                WorkflowRunModel.organization_id == actor.organization_id,
                WorkflowRunModel.version == run.version - 1,
            )
            .values(
                status=run.status.value,
                error_message=run.error_message,
                version=run.version,
                updated_at=run.updated_at,
            )
        )
        result = await self._session.execute(stmt)
        assert isinstance(result, CursorResult)
        if result.rowcount == 0:
            raise RuntimeError("WorkflowRun update failed: concurrent mutation or not found.")
        return run

    async def save_checkpoint(
        self,
        *,
        checkpoint: WorkflowCheckpoint,
    ) -> WorkflowCheckpoint:
        stmt = (
            select(WorkflowCheckpointModel)
            .where(
                WorkflowCheckpointModel.organization_id == checkpoint.organization_id,
                WorkflowCheckpointModel.workflow_run_id == checkpoint.workflow_run_id,
                WorkflowCheckpointModel.sequence == checkpoint.sequence,
            )
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            if existing.node == checkpoint.node and existing.state == checkpoint.state:
                return checkpoint
            raise InvalidTransitionError(
                "Checkpoint conflict: sequence "
                f"{checkpoint.sequence} already exists "
                "with different node or state."
            )

        model = WorkflowCheckpointModel(
            id=checkpoint.id,
            organization_id=checkpoint.organization_id,
            workflow_run_id=checkpoint.workflow_run_id,
            node=checkpoint.node,
            sequence=checkpoint.sequence,
            state=checkpoint.state,
            created_at=checkpoint.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return checkpoint

    async def get_latest_checkpoint(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> WorkflowCheckpoint | None:
        stmt = (
            select(WorkflowCheckpointModel)
            .where(
                WorkflowCheckpointModel.workflow_run_id == run_id,
                WorkflowCheckpointModel.organization_id == actor.organization_id,
            )
            .order_by(WorkflowCheckpointModel.sequence.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return WorkflowCheckpoint(
            id=model.id,
            organization_id=model.organization_id,
            workflow_run_id=model.workflow_run_id,
            node=model.node,
            sequence=model.sequence,
            state=model.state,
            created_at=model.created_at,
        )

    async def create_proposal(
        self,
        *,
        proposal: Proposal,
        initial_version: ProposalVersion,
    ) -> Proposal:
        prop_model = ProposalModel(
            id=proposal.id,
            organization_id=proposal.organization_id,
            workflow_run_id=proposal.workflow_run_id,
            status=proposal.status.value,
            current_version_number=proposal.current_version_number,
            approval_id=proposal.approval_id,
            superseded_approval_id=proposal.superseded_approval_id,
            version=proposal.version,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
        )
        ver_model = ProposalVersionModel(
            id=initial_version.id,
            organization_id=initial_version.organization_id,
            proposal_id=initial_version.proposal_id,
            version_number=initial_version.version_number,
            created_by_membership_id=initial_version.created_by_membership_id,
            content=initial_version.content,
            assumptions=initial_version.assumptions,
            change_summary=initial_version.change_summary,
            field_provenance=initial_version.field_provenance,
            validation_result=initial_version.validation_result,
            source_reference_snapshot=initial_version.source_reference_snapshot,
            workflow_version=initial_version.workflow_version,
            prompt_version=initial_version.prompt_version,
            schema_version=initial_version.schema_version,
            model_reference=initial_version.model_reference,
            verifier_version=initial_version.verifier_version,
            creator_type=initial_version.creator_type,
            created_at=initial_version.created_at,
        )
        self._session.add(prop_model)
        self._session.add(ver_model)
        await self._session.flush()
        return proposal

    async def get_proposal(
        self,
        *,
        actor: AuthenticatedActor,
        proposal_id: UUID,
    ) -> Proposal | None:
        stmt = select(ProposalModel).where(
            ProposalModel.id == proposal_id,
            ProposalModel.organization_id == actor.organization_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Proposal(
            id=model.id,
            organization_id=model.organization_id,
            workflow_run_id=model.workflow_run_id,
            status=ProposalStatus(model.status),
            current_version_number=model.current_version_number,
            approval_id=model.approval_id,
            superseded_approval_id=model.superseded_approval_id,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def get_proposal_by_run_id(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> Proposal | None:
        stmt = select(ProposalModel).where(
            ProposalModel.workflow_run_id == run_id,
            ProposalModel.organization_id == actor.organization_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Proposal(
            id=model.id,
            organization_id=model.organization_id,
            workflow_run_id=model.workflow_run_id,
            status=ProposalStatus(model.status),
            current_version_number=model.current_version_number,
            approval_id=model.approval_id,
            superseded_approval_id=model.superseded_approval_id,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def update_proposal(
        self,
        *,
        actor: AuthenticatedActor,
        proposal: Proposal,
    ) -> Proposal:
        stmt = (
            update(ProposalModel)
            .where(
                ProposalModel.id == proposal.id,
                ProposalModel.organization_id == actor.organization_id,
                ProposalModel.version == proposal.version - 1,
                ProposalModel.current_version_number == proposal.current_version_number,
            )
            .values(
                status=proposal.status.value,
                current_version_number=proposal.current_version_number,
                approval_id=proposal.approval_id,
                superseded_approval_id=proposal.superseded_approval_id,
                version=proposal.version,
                updated_at=proposal.updated_at,
            )
        )
        result = await self._session.execute(stmt)
        assert isinstance(result, CursorResult)
        if result.rowcount == 0:
            raise RuntimeError("Proposal update failed: concurrent mutation or not found.")
        return proposal

    async def edit_proposal(
        self,
        *,
        actor: AuthenticatedActor,
        proposal: Proposal,
        version: ProposalVersion,
        superseded_approval: Approval,
    ) -> Proposal:
        if actor.role != MembershipRole.MANAGER:
            raise PermissionError("Proposal edits require the Manager role.")
        if version.created_by_membership_id != actor.membership_id:
            raise PermissionError("Proposal version must identify the authenticated actor.")
        if (
            proposal.status != ProposalStatus.DRAFT
            or proposal.organization_id != actor.organization_id
            or proposal.id != version.proposal_id
            or proposal.id != superseded_approval.proposal_id
            or proposal.organization_id != version.organization_id
            or proposal.organization_id != superseded_approval.organization_id
            or proposal.current_version_number != version.version_number
            or proposal.superseded_approval_id != superseded_approval.id
            or proposal.approval_id is not None
            or superseded_approval.status != ApprovalStatus.SUPERSEDED
            or superseded_approval.proposal_version_number != version.version_number - 1
        ):
            raise RuntimeError("Proposal edit, version, and superseded Approval do not match.")

        locked_proposal = await self._session.scalar(
            select(ProposalModel)
            .where(
                ProposalModel.id == proposal.id,
                ProposalModel.organization_id == actor.organization_id,
                ProposalModel.status == ProposalStatus.READY_FOR_DECISION.value,
                ProposalModel.approval_id == superseded_approval.id,
                ProposalModel.current_version_number == version.version_number - 1,
                ProposalModel.version == proposal.version - 1,
            )
            .with_for_update()
        )
        if locked_proposal is None:
            raise RuntimeError("Proposal edit failed: concurrent mutation or approval superseded.")

        approval_result = await self._session.execute(
            update(ApprovalModel)
            .where(
                ApprovalModel.id == superseded_approval.id,
                ApprovalModel.organization_id == actor.organization_id,
                ApprovalModel.proposal_id == proposal.id,
                ApprovalModel.status == ApprovalStatus.PENDING.value,
                ApprovalModel.version == superseded_approval.version - 1,
            )
            .values(
                status=superseded_approval.status.value,
                version=superseded_approval.version,
                updated_at=superseded_approval.updated_at,
            )
        )
        assert isinstance(approval_result, CursorResult)
        if approval_result.rowcount == 0:
            raise RuntimeError("Proposal edit failed: Approval concurrency failure.")

        self._session.add(
            ProposalVersionModel(
                id=version.id,
                organization_id=version.organization_id,
                proposal_id=version.proposal_id,
                version_number=version.version_number,
                created_by_membership_id=version.created_by_membership_id,
                content=version.content,
                assumptions=version.assumptions,
                change_summary=version.change_summary,
                field_provenance=version.field_provenance,
                validation_result=version.validation_result,
                source_reference_snapshot=version.source_reference_snapshot,
                workflow_version=version.workflow_version,
                prompt_version=version.prompt_version,
                schema_version=version.schema_version,
                model_reference=version.model_reference,
                verifier_version=version.verifier_version,
                creator_type=version.creator_type,
                created_at=version.created_at,
            )
        )
        await self._session.flush()

        proposal_result = await self._session.execute(
            update(ProposalModel)
            .where(
                ProposalModel.id == proposal.id,
                ProposalModel.organization_id == actor.organization_id,
                ProposalModel.status == ProposalStatus.READY_FOR_DECISION.value,
                ProposalModel.approval_id == superseded_approval.id,
                ProposalModel.current_version_number == version.version_number - 1,
                ProposalModel.version == proposal.version - 1,
            )
            .values(
                status=proposal.status.value,
                current_version_number=proposal.current_version_number,
                approval_id=None,
                superseded_approval_id=superseded_approval.id,
                version=proposal.version,
                updated_at=proposal.updated_at,
            )
        )
        assert isinstance(proposal_result, CursorResult)
        if proposal_result.rowcount == 0:
            raise RuntimeError("Proposal edit failed: concurrent mutation or not found.")
        return proposal

    async def append_proposal_version(
        self,
        *,
        version: ProposalVersion,
    ) -> ProposalVersion:
        model = ProposalVersionModel(
            id=version.id,
            organization_id=version.organization_id,
            proposal_id=version.proposal_id,
            version_number=version.version_number,
            created_by_membership_id=version.created_by_membership_id,
            content=version.content,
            assumptions=version.assumptions,
            change_summary=version.change_summary,
            field_provenance=version.field_provenance,
            validation_result=version.validation_result,
            source_reference_snapshot=version.source_reference_snapshot,
            workflow_version=version.workflow_version,
            prompt_version=version.prompt_version,
            schema_version=version.schema_version,
            model_reference=version.model_reference,
            verifier_version=version.verifier_version,
            creator_type=version.creator_type,
            created_at=version.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return version

    async def get_proposal_version(
        self,
        *,
        actor: AuthenticatedActor,
        proposal_id: UUID,
        version_number: int,
    ) -> ProposalVersion | None:
        stmt = select(ProposalVersionModel).where(
            ProposalVersionModel.proposal_id == proposal_id,
            ProposalVersionModel.version_number == version_number,
            ProposalVersionModel.organization_id == actor.organization_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return ProposalVersion(
            id=model.id,
            organization_id=model.organization_id,
            proposal_id=model.proposal_id,
            version_number=model.version_number,
            created_by_membership_id=model.created_by_membership_id,
            content=model.content,
            assumptions=model.assumptions,
            change_summary=model.change_summary,
            field_provenance=model.field_provenance,
            validation_result=model.validation_result,
            source_reference_snapshot=model.source_reference_snapshot,
            workflow_version=model.workflow_version,
            prompt_version=model.prompt_version,
            schema_version=model.schema_version,
            model_reference=model.model_reference,
            verifier_version=model.verifier_version,
            creator_type=model.creator_type,
            created_at=model.created_at,
        )

    async def create_approval(
        self,
        *,
        approval: Approval,
    ) -> Approval:
        model = ApprovalModel(
            id=approval.id,
            organization_id=approval.organization_id,
            proposal_id=approval.proposal_id,
            proposal_version_number=approval.proposal_version_number,
            status=approval.status.value,
            decided_by_membership_id=approval.decided_by_membership_id,
            decision_reason=approval.decision_reason,
            decided_at=approval.decided_at,
            version=approval.version,
            created_at=approval.created_at,
            updated_at=approval.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return approval

    async def get_approval(
        self,
        *,
        actor: AuthenticatedActor,
        approval_id: UUID,
    ) -> Approval | None:
        stmt = select(ApprovalModel).where(
            ApprovalModel.id == approval_id,
            ApprovalModel.organization_id == actor.organization_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Approval(
            id=model.id,
            organization_id=model.organization_id,
            proposal_id=model.proposal_id,
            proposal_version_number=model.proposal_version_number,
            status=ApprovalStatus(model.status),
            decided_by_membership_id=model.decided_by_membership_id,
            decision_reason=model.decision_reason,
            decided_at=model.decided_at,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def decide_approval(
        self,
        *,
        actor: AuthenticatedActor,
        approval: Approval,
        proposal: Proposal,
    ) -> Approval:
        if actor.role != MembershipRole.MANAGER:
            raise PermissionError("Approval decisions require the Manager role.")
        if approval.decided_by_membership_id != actor.membership_id:
            raise PermissionError("Approval decision must identify the authenticated actor.")
        expected_proposal_status = {
            ApprovalStatus.APPROVED: ProposalStatus.APPROVED,
            ApprovalStatus.REJECTED: ProposalStatus.REJECTED,
        }.get(approval.status)
        if expected_proposal_status is None or proposal.status != expected_proposal_status:
            raise RuntimeError("Approval decision and Proposal terminal status do not match.")
        if (
            proposal.id != approval.proposal_id
            or proposal.organization_id != approval.organization_id
            or proposal.organization_id != actor.organization_id
            or proposal.approval_id != approval.id
            or proposal.current_version_number != approval.proposal_version_number
        ):
            raise RuntimeError("Approval decision and Proposal identity or version do not match.")

        prop_stmt = (
            select(ProposalModel)
            .where(
                ProposalModel.id == approval.proposal_id,
                ProposalModel.organization_id == actor.organization_id,
                ProposalModel.status == ProposalStatus.READY_FOR_DECISION.value,
                ProposalModel.approval_id == approval.id,
                ProposalModel.current_version_number == approval.proposal_version_number,
                ProposalModel.version == proposal.version - 1,
            )
            .with_for_update()
        )
        prop_res = await self._session.execute(prop_stmt)
        if prop_res.scalar_one_or_none() is None:
            raise RuntimeError(
                "Approval update failed: proposal is not READY_FOR_DECISION, "
                "version mismatched, or approval superseded."
            )

        stmt = (
            update(ApprovalModel)
            .where(
                ApprovalModel.id == approval.id,
                ApprovalModel.organization_id == actor.organization_id,
                ApprovalModel.status == ApprovalStatus.PENDING.value,
                ApprovalModel.version == approval.version - 1,
            )
            .values(
                status=approval.status.value,
                decided_by_membership_id=approval.decided_by_membership_id,
                decision_reason=approval.decision_reason,
                decided_at=approval.decided_at,
                version=approval.version,
                updated_at=approval.updated_at,
            )
        )
        result = await self._session.execute(stmt)
        assert isinstance(result, CursorResult)
        if result.rowcount == 0:
            raise RuntimeError(
                "Approval update failed: optimistic concurrency failure, not found, or unpermitted."
            )

        proposal_stmt = (
            update(ProposalModel)
            .where(
                ProposalModel.id == proposal.id,
                ProposalModel.organization_id == actor.organization_id,
                ProposalModel.version == proposal.version - 1,
                ProposalModel.status == ProposalStatus.READY_FOR_DECISION.value,
                ProposalModel.approval_id == approval.id,
            )
            .values(
                status=proposal.status.value,
                version=proposal.version,
                updated_at=proposal.updated_at,
            )
        )
        proposal_result = await self._session.execute(proposal_stmt)
        assert isinstance(proposal_result, CursorResult)
        if proposal_result.rowcount == 0:
            raise RuntimeError("Proposal decision failed: concurrent mutation or not found.")
        return approval

    async def append_event(
        self,
        *,
        event: WorkflowEvent | None = None,
        actor: AuthenticatedActor | None = None,
        run_id: UUID | None = None,
        event_type: str | None = None,
        public_payload: dict[str, Any] | None = None,
    ) -> WorkflowEvent:
        if event is not None:
            org_id = event.organization_id
            target_run_id = event.workflow_run_id
            target_event_type = event.event_type
            payload = event.public_payload
            event_id = event.id
            created_at = event.created_at
        else:
            if (
                actor is None
                or run_id is None
                or event_type is None
                or public_payload is None
            ):
                raise PlanningRunDomainError(
                    "append_event requires either event or "
                    "(actor, run_id, event_type, "
                    "public_payload)."
                )
            org_id = actor.organization_id
            target_run_id = run_id
            target_event_type = event_type
            payload = public_payload
            event_id = uuid4()
            created_at = datetime.now(UTC)

        run_stmt = (
            select(WorkflowRunModel)
            .where(
                WorkflowRunModel.id == target_run_id,
                WorkflowRunModel.organization_id == org_id,
            )
            .with_for_update()
        )
        run_res = await self._session.execute(run_stmt)
        if run_res.scalar_one_or_none() is None:
            raise PlanningRunDomainError(
                "WorkflowRun not found or tenant mismatch."
            )

        # Repository always owns sequence computation
        seq_stmt = select(
            func.coalesce(
                func.max(WorkflowEventModel.sequence), 0,
            ),
        ).where(
            WorkflowEventModel.organization_id == org_id,
            WorkflowEventModel.workflow_run_id == target_run_id,
        )
        max_seq = (
            await self._session.execute(seq_stmt)
        ).scalar_one()
        computed_seq = max_seq + 1

        model = WorkflowEventModel(
            id=event_id,
            organization_id=org_id,
            workflow_run_id=target_run_id,
            sequence=computed_seq,
            event_type=target_event_type,
            public_payload=payload,
            created_at=created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return WorkflowEvent(
            id=model.id,
            organization_id=model.organization_id,
            workflow_run_id=model.workflow_run_id,
            sequence=model.sequence,
            event_type=model.event_type,
            public_payload=model.public_payload,
            created_at=model.created_at,
        )

    async def list_events(
        self,
        *,
        actor: AuthenticatedActor,
        run_id: UUID,
    ) -> list[WorkflowEvent]:
        stmt = (
            select(WorkflowEventModel)
            .where(
                WorkflowEventModel.workflow_run_id == run_id,
                WorkflowEventModel.organization_id == actor.organization_id,
            )
            .order_by(WorkflowEventModel.sequence.asc())
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [
            WorkflowEvent(
                id=m.id,
                organization_id=m.organization_id,
                workflow_run_id=m.workflow_run_id,
                sequence=m.sequence,
                event_type=m.event_type,
                public_payload=m.public_payload,
                created_at=m.created_at,
            )
            for m in models
        ]

    async def record_model_invocation(
        self,
        *,
        invocation: ModelInvocation,
    ) -> ModelInvocation:
        model = ModelInvocationModel(
            id=invocation.id,
            organization_id=invocation.organization_id,
            workflow_run_id=invocation.workflow_run_id,
            provider=invocation.provider,
            model_name=invocation.model_name,
            prompt_version=invocation.prompt_version,
            schema_version=invocation.schema_version,
            invocation_key=invocation.invocation_key,
            prompt_tokens=invocation.prompt_tokens,
            completion_tokens=invocation.completion_tokens,
            duration_ms=invocation.duration_ms,
            status=invocation.status,
            created_at=invocation.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return invocation

    async def add_context_reference(
        self,
        *,
        ref: ContextReference,
    ) -> ContextReference:
        model = ContextReferenceModel(
            id=ref.id,
            organization_id=ref.organization_id,
            workflow_run_id=ref.workflow_run_id,
            resource_type=ref.resource_type,
            resource_id=ref.resource_id,
            provenance_notes=ref.provenance_notes,
            created_at=ref.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return ref

    async def enqueue_outbox_event(
        self,
        *,
        event: OutboxEvent,
        organization_id: UUID,
    ) -> OutboxEvent:
        if organization_id != event.organization_id:
            raise PlanningRunDomainError(
                "Organization ID mismatch in "
                "enqueue_outbox_event."
            )

        stmt = select(OutboxEventModel).where(
            OutboxEventModel.organization_id == event.organization_id,
            OutboxEventModel.event_id == event.event_id,
        ).with_for_update()
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            if (
                existing.event_type == event.event_type
                and existing.aggregate_type == event.aggregate_type
                and existing.aggregate_id == event.aggregate_id
                and existing.payload == event.payload
            ):
                return OutboxEvent(
                    id=existing.id,
                    organization_id=existing.organization_id,
                    event_id=existing.event_id,
                    event_type=existing.event_type,
                    aggregate_type=existing.aggregate_type,
                    aggregate_id=existing.aggregate_id,
                    payload=existing.payload,
                    status=OutboxStatus(existing.status),
                    envelope_version=existing.envelope_version,
                    attempt_count=existing.attempt_count,
                    max_attempts=existing.max_attempts,
                    available_at=existing.available_at,
                    published_at=existing.published_at,
                    last_error_code=existing.last_error_code,
                    last_error=existing.last_error,
                    locked_by_worker_id=existing.locked_by_worker_id,
                    lease_until=existing.lease_until,
                    occurred_at=existing.occurred_at,
                    created_at=existing.created_at,
                )
            raise PlanningRunDomainError(
                f"Conflict: Outbox event {event.event_id} "
                "exists with different attributes."
            )

        model = OutboxEventModel(
            id=event.id,
            organization_id=event.organization_id,
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            status=event.status.value,
            envelope_version=event.envelope_version,
            attempt_count=event.attempt_count,
            max_attempts=event.max_attempts,
            available_at=event.available_at,
            published_at=event.published_at,
            last_error_code=event.last_error_code,
            last_error=event.last_error,
            locked_by_worker_id=event.locked_by_worker_id,
            lease_until=event.lease_until,
            occurred_at=event.occurred_at,
            created_at=event.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return event

    async def claim_pending_outbox_events(
        self,
        *,
        organization_id: UUID,
        worker_id: str,
        limit: int,
        now: datetime,
        lease_until: datetime,
    ) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEventModel)
            .where(
                OutboxEventModel.organization_id == organization_id,
                OutboxEventModel.attempt_count < OutboxEventModel.max_attempts,
                (
                    (OutboxEventModel.status == OutboxStatus.PENDING.value)
                    & (OutboxEventModel.available_at <= now)
                )
                | (
                    (OutboxEventModel.status == OutboxStatus.DISPATCHING.value)
                    & (
                        OutboxEventModel.lease_until.is_(None)
                        | (OutboxEventModel.lease_until < now)
                    )
                ),
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        claimed: list[OutboxEvent] = []
        for model in models:
            model.status = OutboxStatus.DISPATCHING.value
            model.locked_by_worker_id = worker_id
            model.lease_until = lease_until
            model.attempt_count += 1
            claimed.append(
                OutboxEvent(
                    id=model.id,
                    organization_id=model.organization_id,
                    event_id=model.event_id,
                    event_type=model.event_type,
                    aggregate_type=model.aggregate_type,
                    aggregate_id=model.aggregate_id,
                    payload=model.payload,
                    status=OutboxStatus.DISPATCHING,
                    envelope_version=model.envelope_version,
                    attempt_count=model.attempt_count,
                    max_attempts=model.max_attempts,
                    available_at=model.available_at,
                    published_at=model.published_at,
                    last_error_code=model.last_error_code,
                    last_error=model.last_error,
                    locked_by_worker_id=model.locked_by_worker_id,
                    lease_until=model.lease_until,
                    occurred_at=model.occurred_at,
                    created_at=model.created_at,
                )
            )
        await self._session.flush()
        return claimed

    async def mark_outbox_event_published(
        self,
        *,
        organization_id: UUID,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        published_at: datetime,
    ) -> None:
        stmt = (
            update(OutboxEventModel)
            .where(
                OutboxEventModel.organization_id == organization_id,
                OutboxEventModel.event_id == event_id,
                OutboxEventModel.locked_by_worker_id == worker_id,
                OutboxEventModel.status == OutboxStatus.DISPATCHING.value,
                OutboxEventModel.lease_until.is_not(None),
                OutboxEventModel.lease_until >= now,
            )
            .values(
                status=OutboxStatus.DISPATCHED.value,
                published_at=published_at,
                locked_by_worker_id=None,
                lease_until=None,
            )
        )
        result = await self._session.execute(stmt)
        assert isinstance(result, CursorResult)
        if result.rowcount == 0:
            raise PlanningRunDomainError(
                "Outbox publish failed: lease expired, "
                "wrong worker, or event not DISPATCHING."
            )

    async def record_outbox_event_failure(
        self,
        *,
        organization_id: UUID,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        error_code: str,
        error_message: str,
        next_available_at: datetime,
    ) -> None:
        stmt = (
            select(OutboxEventModel)
            .where(
                OutboxEventModel.organization_id == organization_id,
                OutboxEventModel.event_id == event_id,
                OutboxEventModel.locked_by_worker_id == worker_id,
                OutboxEventModel.status == OutboxStatus.DISPATCHING.value,
                OutboxEventModel.lease_until.is_not(None),
                OutboxEventModel.lease_until >= now,
            )
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise PlanningRunDomainError(
                "Outbox failure record failed: "
                "lease expired, wrong worker, "
                "or event not DISPATCHING."
            )

        new_status = (
            OutboxStatus.PENDING.value
            if model.attempt_count < model.max_attempts
            else OutboxStatus.FAILED.value
        )
        model.status = new_status
        model.last_error_code = error_code
        model.last_error = error_message
        model.available_at = next_available_at
        model.locked_by_worker_id = None
        model.lease_until = None
        await self._session.flush()

    async def claim_job(
        self,
        *,
        organization_id: UUID | None = None,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> WorkflowJob | None:
        conditions = [
            WorkflowJobModel.attempt_count < WorkflowJobModel.max_attempts,
            (WorkflowJobModel.status == WorkflowJobStatus.QUEUED.value)
            | (
                (WorkflowJobModel.status == WorkflowJobStatus.RUNNING.value)
                & (WorkflowJobModel.lease_until < now)
            ),
            WorkflowJobModel.available_at <= now,
        ]
        if organization_id is not None:
            conditions.append(WorkflowJobModel.organization_id == organization_id)

        stmt = (
            select(WorkflowJobModel)
            .where(*conditions)
            .order_by(WorkflowJobModel.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None

        model.status = WorkflowJobStatus.RUNNING.value
        model.locked_by_worker_id = worker_id
        model.lease_until = lease_until
        model.attempt_count += 1
        model.updated_at = now
        await self._session.flush()

        return WorkflowJob(
            id=model.id,
            organization_id=model.organization_id,
            workflow_run_id=model.workflow_run_id,
            job_type=model.job_type,
            status=WorkflowJobStatus.RUNNING,
            payload=model.payload,
            attempt_count=model.attempt_count,
            max_attempts=model.max_attempts,
            available_at=model.available_at,
            locked_by_worker_id=model.locked_by_worker_id,
            lease_until=model.lease_until,
            last_error=model.last_error,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def complete_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
    ) -> None:
        stmt = (
            update(WorkflowJobModel)
            .where(
                WorkflowJobModel.id == job_id,
                WorkflowJobModel.locked_by_worker_id == worker_id,
            )
            .values(
                status=WorkflowJobStatus.COMPLETED.value,
                locked_by_worker_id=None,
                lease_until=None,
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.execute(stmt)

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_message: str,
        next_available_at: datetime,
    ) -> None:
        stmt = (
            select(WorkflowJobModel)
            .where(
                WorkflowJobModel.id == job_id,
                WorkflowJobModel.locked_by_worker_id == worker_id,
            )
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return

        new_status = (
            WorkflowJobStatus.QUEUED.value
            if model.attempt_count < model.max_attempts
            else WorkflowJobStatus.FAILED.value
        )
        model.status = new_status
        model.last_error = error_message
        model.available_at = next_available_at
        model.locked_by_worker_id = None
        model.lease_until = None
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
