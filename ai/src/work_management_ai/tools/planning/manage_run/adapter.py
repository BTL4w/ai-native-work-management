"""Typed Tool adapter for backend-owned Planning application services."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from work_management_ai.runtime.contracts import (
    ContextReference,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from work_management_ai.tools.planning.manage_run.contracts import (
    PlanningRunApplicationPort,
    PlanningRunToolInput,
)


class PlanningRunToolAdapter:
    def __init__(self, *, application: PlanningRunApplicationPort) -> None:
        self._application = application

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.tool_id != "planning.manage_run" or request.tool_version != "1.0.0":
            return ToolExecutionResult(
                status="REJECTED", typed_output={}, safe_error_code="TOOL_IDENTITY_MISMATCH"
            )
        try:
            value = PlanningRunToolInput.model_validate(request.typed_input)
        except ValidationError:
            return ToolExecutionResult(
                status="REJECTED", typed_output={}, safe_error_code="PLANNING_INPUT_INVALID"
            )
        output = await self._application.manage_run(
            actor=request.actor,
            value=value,
            idempotency_key=request.idempotency_key,
        )
        resource_id = output.proposal_id or output.workflow_run_id
        resource_type = "PROPOSAL" if output.proposal_id is not None else "WORKFLOW_RUN"
        evidence = (
            ContextReference(
                reference_id=uuid5(
                    NAMESPACE_URL,
                    f"planning:{resource_type}:{resource_id}:{output.proposal_version}",
                ),
                organization_id=request.actor.organization_id,
                resource_type=resource_type,
                resource_id=resource_id,
                version=output.proposal_version,
                observed_at=datetime.now(UTC),
            ),
        )
        return ToolExecutionResult(
            status="SUCCEEDED",
            typed_output=output.model_dump(mode="json"),
            evidence=evidence,
        )
