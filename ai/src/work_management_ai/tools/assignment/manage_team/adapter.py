"""Application-service-only adapter for deterministic team proposals."""

from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from work_management_ai.agents.assignment.contracts import TeamRecommendationSnapshot
from work_management_ai.runtime.contracts import (
    ContextReference,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from work_management_ai.tools.assignment.manage_team.contracts import (
    ManageTeamApplicationPort,
    ManageTeamInput,
    ManageTeamOutput,
)


class ManageTeamToolAdapter:
    def __init__(self, *, application: ManageTeamApplicationPort) -> None:
        self._application = application

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.tool_id != "assignment.manage_team" or request.tool_version != "1.0.0":
            return _rejected("TOOL_IDENTITY_MISMATCH")
        try:
            value = ManageTeamInput.model_validate(request.typed_input)
        except ValidationError:
            return _rejected("TOOL_INPUT_INVALID")
        output = await self._application.manage_team(
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
                    reference_id=uuid5(NAMESPACE_URL, _evidence_identity(output)),
                    organization_id=output.organization_id,
                    resource_type=(
                        "TEAM_RECOMMENDATION"
                        if isinstance(output, TeamRecommendationSnapshot)
                        else "TEAM_REQUIREMENTS"
                    ),
                    resource_id=(
                        output.recommendation_id
                        if isinstance(output, TeamRecommendationSnapshot)
                        else output.requirement_set_id
                    ),
                    version=(
                        output.version
                        if isinstance(output, TeamRecommendationSnapshot)
                        else output.requirement_version
                    ),
                    observed_at=output.observed_at,
                ),
            ),
        )


def _rejected(code: str) -> ToolExecutionResult:
    return ToolExecutionResult(status="REJECTED", typed_output={}, safe_error_code=code)


def _evidence_identity(output: ManageTeamOutput) -> str:
    if isinstance(output, TeamRecommendationSnapshot):
        return f"team-recommendation:{output.recommendation_id}:v{output.version}"
    return f"team-requirements:{output.requirement_set_id}:v{output.requirement_version}"
