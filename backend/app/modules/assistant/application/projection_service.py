"""Idempotent projection of committed focused workflow events into chat."""

from typing import Any
from uuid import UUID

from app.modules.assistant.application.ports import (
    AssistantTransactionFactory,
    LinkedWorkflowEvent,
)


class AssistantProjectionService:
    """Map safe committed events without invoking AI or business mutations."""

    def __init__(self, *, transaction_factory: AssistantTransactionFactory) -> None:
        self._transactions = transaction_factory

    async def project_once(self, *, organization_id: UUID, limit: int = 50) -> int:
        bounded = min(max(limit, 1), 50)
        async with self._transactions(organization_id) as transaction:
            items = await transaction.repository.list_unprojected_workflow_events(
                organization_id=organization_id,
                limit=bounded,
            )
            projected = 0
            for item in items:
                blocks, status, safe_error = self._map(item)
                if await transaction.repository.project_workflow_event(
                    item=item,
                    blocks=blocks,
                    status=status,
                    safe_error_code=safe_error,
                ):
                    projected += 1
            await transaction.commit()
            return projected

    @staticmethod
    def _map(
        item: LinkedWorkflowEvent,
    ) -> tuple[tuple[dict[str, Any], ...], str | None, str | None]:
        event = item.event
        payload = event.public_payload
        if event.event_type in {"workflow.needs_input", "manager.input_required"}:
            return (
                (
                    {
                        "kind": "question",
                        "question": str(
                            payload.get(
                                "question",
                                "Additional planning input is required.",
                            )
                        ),
                        "response_context": {
                            "workflow_run_id": str(event.workflow_run_id),
                        },
                    },
                ),
                "AWAITING_INPUT",
                None,
            )
        if event.event_type == "proposal.ready":
            return (
                (
                    {
                        "kind": "proposal",
                        "workflow_run_id": str(event.workflow_run_id),
                        "proposal_id": str(payload.get("proposal_id", "")),
                        "proposal_version": int(payload.get("version", 0)),
                        "state": "READY_FOR_DECISION",
                        "can_approve": bool(payload.get("can_approve", False)),
                        "read_only": False,
                    },
                ),
                "AWAITING_HUMAN",
                None,
            )
        if event.event_type == "proposal.validation_failed":
            return (
                (
                    {
                        "kind": "proposal",
                        "workflow_run_id": str(event.workflow_run_id),
                        "proposal_id": str(payload.get("proposal_id", "")),
                        "proposal_version": int(payload.get("version", 0)),
                        "state": "VALIDATION_FAILED",
                        "can_approve": False,
                        "read_only": False,
                        "error_codes": list(payload.get("error_codes", [])),
                        "manual_fallback": "PROJECT_TASK_EDITOR",
                    },
                ),
                "AWAITING_HUMAN",
                None,
            )
        if event.event_type in {"proposal.superseded", "proposal.stale"}:
            return (
                (
                    {
                        "kind": "proposal",
                        "workflow_run_id": str(event.workflow_run_id),
                        "proposal_id": str(payload.get("proposal_id", "")),
                        "proposal_version": int(payload.get("base_version", 0)),
                        "current_version": int(payload.get("current_version", 0)),
                        "state": (
                            "SUPERSEDED" if event.event_type.endswith("superseded") else "STALE"
                        ),
                        "read_only": True,
                    },
                ),
                "AWAITING_HUMAN",
                None,
            )
        if event.event_type == "workflow.completed":
            return (
                (
                    {
                        "kind": "decision_result",
                        "workflow_run_id": str(event.workflow_run_id),
                        "decision": str(payload.get("decision", "UNKNOWN")),
                        "proposal_id": str(payload.get("proposal_id", "")),
                        "proposal_version": int(payload.get("proposal_version", 0)),
                    },
                ),
                "COMPLETED",
                None,
            )
        if event.event_type in {"workflow.failed", "proposal.revision_failed"}:
            code = str(payload.get("safe_error_code", "AI_WORKFLOW_UNAVAILABLE"))
            return (
                (
                    {
                        "kind": "safe_error",
                        "code": code,
                        "message_key": "ai.error.workflowUnavailable",
                        "manual_fallback": "PROJECT_TASK_EDITOR",
                    },
                ),
                "FAILED" if event.event_type == "workflow.failed" else "AWAITING_HUMAN",
                code if event.event_type == "workflow.failed" else None,
            )
        return (
            (
                {
                    "kind": "activity",
                    "label_key": f"ai.activity.{event.event_type.replace('.', '_')}",
                    "status": "COMPLETED",
                    "agent_id": "planning",
                },
            ),
            None,
            None,
        )
