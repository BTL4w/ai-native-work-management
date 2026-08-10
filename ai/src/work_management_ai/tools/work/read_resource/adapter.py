"""Non-disclosing resource-read Tool adapter."""

from uuid import NAMESPACE_URL, uuid5

from work_management_ai.agents.work_intelligence.contracts import EvidenceItem
from work_management_ai.runtime.contracts import (
    ContextReference,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from work_management_ai.tools.work.read_resource.contracts import (
    ReadResourceApplicationPort,
    ReadResourceInput,
    ReadResourceOutput,
    ResourceReadRecord,
)


class ReadResourceToolAdapter:
    def __init__(self, *, application: ReadResourceApplicationPort) -> None:
        self._application = application

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.tool_id != "work.read_resource" or request.tool_version != "1.0.0":
            return ToolExecutionResult(
                status="REJECTED", typed_output={}, safe_error_code="TOOL_IDENTITY_MISMATCH"
            )
        value = ReadResourceInput.model_validate(request.typed_input)
        resolution = await self._application.resolve_resource(actor=request.actor, value=value)
        records = resolution.records if resolution.status == "UNIQUE" else ()
        evidence = tuple(_to_evidence(record) for record in records)
        output = ReadResourceOutput(resolution=resolution.status, evidence=evidence)
        return ToolExecutionResult(
            status="SUCCEEDED",
            typed_output=output.model_dump(mode="json"),
            evidence=tuple(_to_context(item, request) for item in evidence),
        )


def _to_evidence(record: ResourceReadRecord) -> EvidenceItem:
    version = record.resource_version if record.resource_version is not None else "unknown"
    return EvidenceItem(
        evidence_id=f"{record.resource_type.lower()}:{record.resource_id}:v{version}",
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        resource_version=record.resource_version,
        fields=record.fields,
        observed_at=record.observed_at,
    )


def _to_context(item: EvidenceItem, request: ToolExecutionRequest) -> ContextReference:
    return ContextReference(
        reference_id=uuid5(NAMESPACE_URL, item.evidence_id),
        organization_id=request.actor.organization_id,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        version=item.resource_version,
        observed_at=item.observed_at,
    )
