"""Tool adapter around a tenant-aware Work application-service port."""

from uuid import NAMESPACE_URL, uuid5

from work_management_ai.agents.work_intelligence.contracts import EvidenceItem
from work_management_ai.runtime.contracts import (
    ContextReference,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from work_management_ai.tools.work.read_my_tasks.contracts import (
    ReadMyTasksApplicationPort,
    ReadMyTasksInput,
    ReadMyTasksOutput,
    TaskReadRecord,
)


class ReadMyTasksToolAdapter:
    def __init__(self, *, application: ReadMyTasksApplicationPort) -> None:
        self._application = application

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.tool_id != "work.read_my_tasks" or request.tool_version != "1.0.0":
            return ToolExecutionResult(
                status="REJECTED", typed_output={}, safe_error_code="TOOL_IDENTITY_MISMATCH"
            )
        value = ReadMyTasksInput.model_validate(request.typed_input)
        records = await self._application.read_my_tasks(
            actor=request.actor,
            status=value.status,
            due_from=value.due_from,
            due_to=value.due_to,
            limit=value.limit,
        )
        ordered = tuple(sorted(records, key=_task_order))
        evidence = tuple(_to_evidence(record) for record in ordered)
        next_task = next(
            (record for record in ordered if record.status in {"IN_PROGRESS", "TO_DO"}),
            None,
        )
        output = ReadMyTasksOutput(
            resolution="UNIQUE" if evidence else "NOT_FOUND",
            evidence=evidence,
            next_task_id=next_task.id if next_task is not None else None,
        )
        return ToolExecutionResult(
            status="SUCCEEDED",
            typed_output=output.model_dump(mode="json"),
            evidence=tuple(_to_context(item, request) for item in evidence),
        )


def _task_order(record: TaskReadRecord) -> tuple[object, ...]:
    status_order = {"IN_PROGRESS": 0, "TO_DO": 1, "DONE": 2}
    return (
        status_order[record.status],
        record.due_date is None,
        record.due_date,
        record.created_at,
        record.id,
    )


def _to_evidence(record: TaskReadRecord) -> EvidenceItem:
    evidence_id = f"task:{record.id}:v{record.version}"
    return EvidenceItem(
        evidence_id=evidence_id,
        resource_type="TASK",
        resource_id=record.id,
        resource_version=record.version,
        fields={
            "project_id": str(record.project_id),
            "title": record.title,
            "status": record.status,
            "due_date": record.due_date.isoformat() if record.due_date is not None else None,
            "created_at": record.created_at.isoformat(),
        },
        observed_at=record.updated_at,
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
