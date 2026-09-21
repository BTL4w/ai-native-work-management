"""Application-service-only workload Tool adapter."""

from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from work_management_ai.runtime.contracts import (
    ContextReference,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from work_management_ai.tools.assignment.read_workload.contracts import (
    ReadWorkloadApplicationPort,
    ReadWorkloadInput,
)


class ReadWorkloadToolAdapter:
    def __init__(self, *, application: ReadWorkloadApplicationPort) -> None:
        self._application = application

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.tool_id != "assignment.read_workload" or request.tool_version != "1.0.0":
            return _rejected("TOOL_IDENTITY_MISMATCH")
        try:
            value = ReadWorkloadInput.model_validate(request.typed_input)
        except ValidationError:
            return _rejected("TOOL_INPUT_INVALID")
        output = await self._application.read_workload(actor=request.actor, value=value)
        if output.organization_id != request.actor.organization_id:
            return _rejected("TOOL_TENANT_MISMATCH")
        return ToolExecutionResult(
            status="SUCCEEDED",
            typed_output=output.model_dump(mode="json"),
            evidence=(
                ContextReference(
                    reference_id=uuid5(
                        NAMESPACE_URL,
                        f"project-workload:{output.project_id}:{output.observed_at.isoformat()}",
                    ),
                    organization_id=output.organization_id,
                    resource_type="WORKLOAD",
                    resource_id=output.project_id,
                    observed_at=output.observed_at,
                ),
            ),
        )


def _rejected(code: str) -> ToolExecutionResult:
    return ToolExecutionResult(status="REJECTED", typed_output={}, safe_error_code=code)
