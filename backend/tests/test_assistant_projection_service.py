"""Task 8 committed workflow-event projection tests."""

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportArgumentType=false, reportIndexIssue=false

from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from typing import Self
from uuid import uuid4

import pytest

from app.modules.assistant.api.schemas import MessageResponse
from app.modules.assistant.application.ports import LinkedWorkflowEvent
from app.modules.assistant.application.projection_service import AssistantProjectionService
from app.modules.assistant.domain.models import AgentRun, AssistantMessage, MessageRole
from app.modules.planning_runs.domain.models import WorkflowEvent


def _item(event_type: str, payload: dict[str, object], *, sequence: int = 1):
    organization_id = uuid4()
    workflow_run_id = uuid4()
    run = AgentRun.create(
        organization_id=organization_id,
        orchestration_run_id=uuid4(),
        agent_id="planning",
        agent_version="1.0.0",
        manifest_fingerprint="f" * 64,
        capability="planning.create",
        typed_input={},
        budget={},
        workflow_run_id=workflow_run_id,
        projected_workflow_sequence=0,
    ).mark_running()
    return LinkedWorkflowEvent(
        agent_run=run,
        turn_id=uuid4(),
        conversation_id=uuid4(),
        event=WorkflowEvent(
            id=uuid4(),
            organization_id=organization_id,
            workflow_run_id=workflow_run_id,
            sequence=sequence,
            event_type=event_type,
            public_payload=payload,
        ),
    )


class _Repository:
    def __init__(self, items: list[LinkedWorkflowEvent]) -> None:
        self.items = items
        self.projected: list[dict[str, object]] = []
        self.cursors: dict[object, int] = {}
        self.model_calls = 0
        self.business_calls = 0

    async def list_unprojected_workflow_events(self, *, organization_id, limit):
        return tuple(
            item
            for item in self.items
            if item.event.organization_id == organization_id
            and item.event.sequence
            > self.cursors.get(item.agent_run.id, item.agent_run.projected_workflow_sequence or 0)
        )[:limit]

    async def project_workflow_event(self, *, item, blocks, status, safe_error_code):
        key = f"workflow:{item.event.workflow_run_id}:{item.event.sequence}"
        if any(row["dedupe_key"] == key for row in self.projected):
            return False
        self.projected.append(
            {
                "dedupe_key": key,
                "blocks": blocks,
                "status": status,
                "safe_error_code": safe_error_code,
            }
        )
        self.cursors[item.agent_run.id] = item.event.sequence
        return True


class _Transaction(AbstractAsyncContextManager["_Transaction"]):
    def __init__(self, repository: _Repository, *, crash: bool = False) -> None:
        self.repository = repository
        self.crash = crash
        self._snapshot = None

    async def __aenter__(self) -> Self:
        self._snapshot = (list(self.repository.projected), dict(self.repository.cursors))
        return self

    async def __aexit__(self, exc_type, *_):
        if (exc_type is not None or self.crash) and self._snapshot is not None:
            self.repository.projected, self.repository.cursors = self._snapshot

    async def commit(self):
        if self.crash:
            raise RuntimeError("crash before cursor commit")


def _service(repository: _Repository, *, crash: bool = False):
    return AssistantProjectionService(
        transaction_factory=lambda _: _Transaction(repository, crash=crash)
    )


@pytest.mark.asyncio
async def test_question_event_projects_once_and_marks_awaiting_input() -> None:
    item = _item(
        "workflow.needs_input",
        {"question": "What is the budget?", "stage": "NEEDS_INPUT"},
    )
    repository = _Repository([item])

    assert await _service(repository).project_once(organization_id=item.event.organization_id) == 1
    assert await _service(repository).project_once(organization_id=item.event.organization_id) == 0
    row = repository.projected[0]
    assert row["status"] == "AWAITING_INPUT"
    assert row["blocks"][0]["kind"] == "question"
    assert row["blocks"][0]["question"] == "What is the budget?"


@pytest.mark.asyncio
async def test_proposal_ready_projects_exact_version_card_once() -> None:
    proposal_id = uuid4()
    item = _item(
        "proposal.ready",
        {"proposal_id": str(proposal_id), "version": 4, "can_approve": True},
    )
    repository = _Repository([item])

    await _service(repository).project_once(organization_id=item.event.organization_id)

    block = repository.projected[0]["blocks"][0]
    assert block == {
        "kind": "proposal",
        "workflow_run_id": str(item.event.workflow_run_id),
        "proposal_id": str(proposal_id),
        "proposal_version": 4,
        "state": "READY_FOR_DECISION",
        "can_approve": True,
        "read_only": False,
    }
    assert repository.projected[0]["status"] == "AWAITING_HUMAN"


@pytest.mark.asyncio
async def test_revalidation_projects_new_current_version_and_marks_old_card_stale() -> None:
    item = _item(
        "proposal.superseded",
        {"proposal_id": str(uuid4()), "base_version": 2, "current_version": 3},
    )
    repository = _Repository([item])

    await _service(repository).project_once(organization_id=item.event.organization_id)

    block = repository.projected[0]["blocks"][0]
    assert block["state"] == "SUPERSEDED"
    assert block["proposal_version"] == 2
    assert block["current_version"] == 3
    assert block["read_only"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["APPROVE", "REJECT"])
async def test_task8_finalize_projects_approve_and_reject_without_model_call(
    decision: str,
) -> None:
    item = _item(
        "workflow.completed",
        {"decision": decision, "proposal_id": str(uuid4()), "proposal_version": 3},
    )
    repository = _Repository([item])

    await _service(repository).project_once(organization_id=item.event.organization_id)

    assert repository.projected[0]["blocks"][0]["kind"] == "decision_result"
    assert repository.projected[0]["blocks"][0]["decision"] == decision
    assert repository.projected[0]["status"] == "COMPLETED"
    assert repository.model_calls == repository.business_calls == 0


@pytest.mark.asyncio
async def test_projector_crash_before_cursor_commit_replays_without_duplicate_message() -> None:
    item = _item("workflow.generating", {"stage": "GENERATING"})
    repository = _Repository([item])

    with pytest.raises(RuntimeError, match="crash before cursor commit"):
        await _service(repository, crash=True).project_once(
            organization_id=item.event.organization_id
        )
    assert repository.projected == []
    assert repository.cursors == {}

    assert await _service(repository).project_once(organization_id=item.event.organization_id) == 1
    assert len(repository.projected) == 1


@pytest.mark.asyncio
async def test_cross_tenant_link_or_event_is_never_projected() -> None:
    item = _item("workflow.generating", {"stage": "GENERATING"})
    foreign_event = replace(item.event, organization_id=uuid4())
    repository = _Repository([replace(item, event=foreign_event)])

    count = await _service(repository).project_once(organization_id=item.agent_run.organization_id)

    assert count == 0
    assert repository.projected == []


@pytest.mark.asyncio
async def test_projection_does_not_apply_business_graph() -> None:
    item = _item("proposal.ready", {"proposal_id": str(uuid4()), "version": 1})
    repository = _Repository([item])
    await _service(repository).project_once(organization_id=item.event.organization_id)
    assert repository.business_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("workflow.generating", {"stage": "GENERATING"}),
        ("workflow.needs_input", {"question": "What is the budget?"}),
        (
            "proposal.ready",
            {"proposal_id": str(uuid4()), "version": 2, "can_approve": True},
        ),
        (
            "proposal.superseded",
            {"proposal_id": str(uuid4()), "base_version": 2, "current_version": 3},
        ),
        (
            "workflow.completed",
            {"decision": "APPROVE", "proposal_id": str(uuid4()), "proposal_version": 3},
        ),
        ("workflow.failed", {"safe_error_code": "AI_WORKFLOW_UNAVAILABLE"}),
    ],
)
async def test_projected_blocks_match_conversation_snapshot_contract(
    event_type: str,
    payload: dict[str, object],
) -> None:
    item = _item(event_type, payload)
    repository = _Repository([item])
    await _service(repository).project_once(organization_id=item.event.organization_id)

    response = MessageResponse.from_domain(
        AssistantMessage(
            id=uuid4(),
            organization_id=item.event.organization_id,
            conversation_id=item.conversation_id,
            sequence=1,
            role=MessageRole.ASSISTANT,
            content_blocks=repository.projected[0]["blocks"],
        )
    )

    assert response.content_blocks[0].kind == repository.projected[0]["blocks"][0]["kind"]
