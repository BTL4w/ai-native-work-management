"""Application-service-only adapter for explicit exact Task assignment."""

from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from work_management_ai.runtime.contracts import (
    ContextReference,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from work_management_ai.tools.assignment.assign_task.contracts import (
    AssignTaskApplicationPort,
    AssignTaskInput,
)


class AssignTaskToolAdapter:
    def __init__(self, *, application: AssignTaskApplicationPort) -> None:
        self._application = application

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.tool_id != "assignment.assign_task" or request.tool_version != "1.0.0":
            return _rejected("TOOL_IDENTITY_MISMATCH")
        try:
            value = AssignTaskInput.model_validate(request.typed_input)
        except ValidationError:
            return _rejected("TOOL_INPUT_INVALID")
        output = await self._application.assign_task(
            actor=request.actor,
            value=value,
            idempotency_key=request.idempotency_key,
        )
        if output.organization_id != request.actor.organization_id:
            return _rejected("TOOL_TENANT_MISMATCH")
        return ToolExecutionResult(
            status="SUCCEEDED",
            typed_output=output.model_dump(mode="json"),
            evidence=(
                ContextReference(
                    reference_id=uuid5(
                        NAMESPACE_URL,
                        f"task-assignment:{output.task_id}:v{output.task_version}",
                    ),
                    organization_id=output.organization_id,
                    resource_type="TASK",
                    resource_id=output.task_id,
                    version=output.task_version,
                    observed_at=output.observed_at,
                ),
            ),
        )


def _rejected(code: str) -> ToolExecutionResult:
    return ToolExecutionResult(status="REJECTED", typed_output={}, safe_error_code=code)
