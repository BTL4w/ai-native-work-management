from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from work_management_ai.runtime.context_manager import ContextManager, ContextSelectionError
from work_management_ai.runtime.contracts import (
    ActorReference,
    AgentBudget,
    AgentHandoff,
    AgentId,
    AgentResult,
    AgentRunStatus,
    ContextReference,
    JsonValue,
    ResponseBlock,
)
from work_management_ai.runtime.memory_manager import MemoryManager, RuntimeMemoryError


def _actor() -> ActorReference:
    return ActorReference(membership_id=uuid4(), organization_id=uuid4())


def _context_reference(*, organization_id: UUID | None = None) -> ContextReference:
    return ContextReference(
        reference_id=uuid4(),
        organization_id=organization_id or uuid4(),
        resource_type="task",
        resource_id=uuid4(),
        version=3,
        fingerprint=None,
        observed_at=datetime.now(UTC),
    )


def test_handoff_rejects_top_level_role_and_tenant_override_fields() -> None:
    actor = _actor()
    base = {
        "orchestration_run_id": uuid4(),
        "parent_agent_run_id": uuid4(),
        "target_agent_id": AgentId.PLANNING,
        "target_agent_version": "1.0.0",
        "capability": "planning.create",
        "objective": "Create a project plan",
        "typed_input": {"brief": "Plan a conference"},
        "context_references": (),
        "actor": actor,
        "budget": AgentBudget(
            max_iterations=4,
            max_tool_calls=3,
            max_handoffs=1,
            max_replans=1,
            timeout_seconds=60,
        ),
        "step_id": "plan-1",
        "idempotency_key": "turn-1:plan-1",
    }

    with pytest.raises(ValidationError):
        AgentHandoff.model_validate({**base, "role": "ADMIN"})
    with pytest.raises(ValidationError):
        AgentHandoff.model_validate({**base, "organization_id": str(uuid4())})


def test_agent_result_rejects_hidden_reasoning_field() -> None:
    with pytest.raises(ValidationError):
        AgentResult.model_validate(
            {
                "agent_id": "planning",
                "agent_version": "1.0.0",
                "status": AgentRunStatus.COMPLETED,
                "typed_output": {"proposal_id": "proposal-1"},
                "iterations_used": 1,
                "tool_calls_used": 0,
                "stop_reason": "completed",
                "hidden_reasoning": "private chain of thought",
            }
        )


def test_response_block_union_rejects_unknown_or_extra_public_fields() -> None:
    adapter: TypeAdapter[ResponseBlock] = TypeAdapter(ResponseBlock)

    block = adapter.validate_python({"kind": "text", "text": "Ready"})
    assert block.kind == "text"
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "text", "text": "Ready", "prompt": "secret"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "reasoning", "text": "private"})


def test_context_manager_bounds_recent_messages_and_references() -> None:
    actor = _actor()
    references = tuple(_context_reference(organization_id=actor.organization_id) for _ in range(3))

    selected = ContextManager(max_references=2, max_recent_messages=2).select(
        actor=actor,
        references=references,
        recent_messages=("oldest", "recent", "latest"),
    )

    assert selected.references == references[:2]
    assert selected.recent_messages == ("recent", "latest")


def test_context_manager_rejects_cross_tenant_reference() -> None:
    actor = _actor()

    with pytest.raises(ContextSelectionError, match="CONTEXT_TENANT_MISMATCH"):
        ContextManager().select(
            actor=actor,
            references=(_context_reference(),),
            recent_messages=(),
        )


@pytest.mark.parametrize(
    "state",
    [
        {"hidden_reasoning": "private"},
        {"nested": {"organization_id": str(uuid4())}},
        {"messages": [{"role": "ADMIN"}]},
    ],
)
def test_memory_manager_rejects_reasoning_and_authority_claims(state: object) -> None:
    with pytest.raises(RuntimeMemoryError, match="RESERVED_MEMORY_KEY"):
        MemoryManager().checkpoint(cast(dict[str, JsonValue], state))


def test_memory_manager_returns_an_immutable_typed_snapshot() -> None:
    state: dict[str, JsonValue] = {
        "step": "collect_context",
        "attempt": 1,
        "items": ["task-1"],
    }

    checkpoint = MemoryManager().checkpoint(state)
    state["step"] = "tampered"

    assert checkpoint.state == {
        "step": "collect_context",
        "attempt": 1,
        "items": ["task-1"],
    }
