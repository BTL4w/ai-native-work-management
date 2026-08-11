"""Domain lifecycle and bounded-payload tests for durable Assistant state."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.assistant.domain.models import (
    AgentRun,
    AgentRunStatus,
    AssistantConversation,
    AssistantDomainError,
    AssistantEvent,
    AssistantJob,
    AssistantJobStatus,
    AssistantMessage,
    AssistantTurn,
    AssistantTurnStatus,
    InvalidAssistantTransitionError,
    MessageRole,
    OrchestrationRun,
    OrchestrationRunStatus,
)


def test_conversation_sequences_are_strictly_monotonic() -> None:
    conversation = AssistantConversation.create(
        organization_id=uuid4(), owner_membership_id=uuid4(), locale="vi"
    )

    conversation = conversation.record_message(1)
    conversation = conversation.record_event(1)

    assert conversation.last_message_sequence == 1
    assert conversation.last_event_sequence == 1
    assert conversation.version == 3
    with pytest.raises(AssistantDomainError, match="MESSAGE_SEQUENCE_INVALID"):
        conversation.record_message(3)
    with pytest.raises(AssistantDomainError, match="EVENT_SEQUENCE_INVALID"):
        conversation.record_event(1)


def test_message_rejects_text_over_8000_characters() -> None:
    with pytest.raises(AssistantDomainError, match="MESSAGE_TEXT_LIMIT_EXCEEDED"):
        AssistantMessage(
            id=uuid4(),
            organization_id=uuid4(),
            conversation_id=uuid4(),
            sequence=1,
            role=MessageRole.USER,
            content_blocks=({"kind": "text", "text": "x" * 8_001},),
        )


def test_event_rejects_payload_over_64_kib() -> None:
    with pytest.raises(AssistantDomainError, match="EVENT_PAYLOAD_LIMIT_EXCEEDED"):
        AssistantEvent(
            id=uuid4(),
            organization_id=uuid4(),
            conversation_id=uuid4(),
            sequence=1,
            event_type="assistant.turn.updated.v1",
            public_payload={"value": "x" * (64 * 1024)},
        )


def test_turn_allows_human_wait_and_completion_but_terminal_is_immutable() -> None:
    turn = AssistantTurn.create(
        organization_id=uuid4(),
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        actor_membership_id=uuid4(),
        objective="Create a permitted project proposal",
        locale="en",
    )

    completed = turn.mark_running().mark_awaiting_human().mark_running().mark_completed()

    assert completed.status is AssistantTurnStatus.COMPLETED
    with pytest.raises(InvalidAssistantTransitionError):
        completed.mark_failed("SAFE_FAILURE")


def test_orchestration_plan_is_bounded_to_eight_steps() -> None:
    with pytest.raises(AssistantDomainError, match="ORCHESTRATION_PLAN_LIMIT_EXCEEDED"):
        OrchestrationRun.create(
            organization_id=uuid4(),
            turn_id=uuid4(),
            orchestrator_version="1.0.0",
            orchestrator_fingerprint="abc",
            execution_plan={"steps": [{"step_id": str(index)} for index in range(9)]},
            budget={"max_iterations": 8},
        )


def test_orchestration_and_agent_terminal_states_are_immutable() -> None:
    orchestration = OrchestrationRun.create(
        organization_id=uuid4(),
        turn_id=uuid4(),
        orchestrator_version="1.0.0",
        orchestrator_fingerprint="abc",
        execution_plan={"steps": []},
        budget={"max_iterations": 8},
    ).mark_running()
    agent = AgentRun.create(
        organization_id=orchestration.organization_id,
        orchestration_run_id=orchestration.id,
        agent_id="planning",
        agent_version="1.0.0",
        manifest_fingerprint="manifest",
        capability="planning.create",
        typed_input={"operation": "CREATE"},
        budget={"max_iterations": 8},
    ).mark_running()

    completed_orchestration = orchestration.mark_completed("COMPLETED")
    completed_agent = agent.mark_completed(
        typed_output={"awaiting": "MANAGER_DECISION"}, stop_reason="AWAITING_HUMAN"
    )

    assert completed_orchestration.status is OrchestrationRunStatus.COMPLETED
    assert completed_agent.status is AgentRunStatus.COMPLETED
    with pytest.raises(InvalidAssistantTransitionError):
        completed_orchestration.mark_running()
    with pytest.raises(InvalidAssistantTransitionError):
        completed_agent.mark_failed("LATE_FAILURE")


@pytest.mark.parametrize("unsafe", ["private provider detail", "sql:error", "", "has space"])
def test_safe_error_code_rejects_internal_text(unsafe: str) -> None:
    turn = AssistantTurn.create(
        organization_id=uuid4(),
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        actor_membership_id=uuid4(),
        objective="Question",
        locale="en",
    ).mark_running()

    with pytest.raises(AssistantDomainError, match="SAFE_ERROR_CODE_INVALID"):
        turn.mark_failed(unsafe)


def test_job_claim_retry_and_terminal_transitions_are_bounded() -> None:
    now = datetime.now(UTC)
    job = AssistantJob.create(
        organization_id=uuid4(),
        conversation_id=uuid4(),
        turn_id=uuid4(),
        orchestration_run_id=uuid4(),
        requester_membership_id=uuid4(),
        payload={"turn_id": str(uuid4())},
        max_attempts=2,
        available_at=now,
    )

    claimed = job.claim(worker_id="worker-1", lease_until=now + timedelta(minutes=1), now=now)
    retried = claimed.fail(
        worker_id="worker-1",
        error_code="ASSISTANT_STEP_FAILED",
        next_available_at=now + timedelta(minutes=2),
        now=now,
    )
    claimed_again = retried.claim(
        worker_id="worker-2", lease_until=now + timedelta(minutes=3), now=now + timedelta(minutes=2)
    )
    completed = claimed_again.complete(worker_id="worker-2", now=now + timedelta(minutes=2))

    assert completed.status is AssistantJobStatus.COMPLETED
    assert completed.attempt_count == 2
    with pytest.raises(InvalidAssistantTransitionError):
        completed.claim(worker_id="worker-3", lease_until=now + timedelta(minutes=4), now=now)
