"""ASGI contract coverage for the Task 6 Assistant conversation API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.modules.assistant.api.dependencies import (
    get_assistant_event_service,
    get_assistant_service,
)
from app.modules.assistant.application.ports import (
    AssistantConversationMutationResult,
    AssistantConversationSnapshot,
    AssistantTurnMutationResult,
)
from app.modules.assistant.application.service import AssistantServiceError, ResourceNotFoundError
from app.modules.assistant.domain.models import (
    AssistantConversation,
    AssistantEvent,
    AssistantJob,
    AssistantMessage,
    AssistantTurn,
    MessageRole,
    OrchestrationRun,
)
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole


def _actor(role: MembershipRole = MembershipRole.EMPLOYEE) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="assistant@example.test",
        display_name="Assistant user",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Assistant tenant",
        role=role,
    )


class StubAssistantService:
    def __init__(self, actor: AuthenticatedActor) -> None:
        self.actor = actor
        self.conversation = AssistantConversation.create(
            organization_id=actor.organization_id,
            owner_membership_id=actor.membership_id,
            locale="en",
            title="My work",
        )
        self.error: Exception | None = None
        self.last_post: dict[str, Any] | None = None

    async def create_conversation(self, **_: Any) -> AssistantConversationMutationResult:
        if self.error is not None:
            raise self.error
        return AssistantConversationMutationResult(self.conversation, False)

    async def list_conversations(self, **_: Any) -> list[AssistantConversation]:
        if self.error is not None:
            raise self.error
        return [self.conversation]

    async def get_conversation(self, **_: Any) -> AssistantConversationSnapshot:
        if self.error is not None:
            raise self.error
        now = datetime.now(UTC)
        message = AssistantMessage(
            id=uuid4(),
            organization_id=self.actor.organization_id,
            conversation_id=self.conversation.id,
            sequence=1,
            role=MessageRole.ASSISTANT,
            content_blocks=({"kind": "safe_error", "code": "SAFE", "message_key": "ai.safe"},),
            created_at=now,
        )
        return AssistantConversationSnapshot(self.conversation, (message,), (), (), ())

    async def post_message(self, **values: Any) -> AssistantTurnMutationResult:
        if self.error is not None:
            raise self.error
        self.last_post = values
        now = datetime.now(UTC)
        message_id, turn_id, run_id = uuid4(), uuid4(), uuid4()
        message = AssistantMessage(
            id=message_id,
            organization_id=self.actor.organization_id,
            conversation_id=self.conversation.id,
            sequence=1,
            role=MessageRole.USER,
            content_blocks=({"kind": "text", "text": values["message"]},),
            created_by_membership_id=self.actor.membership_id,
            turn_id=turn_id,
            created_at=now,
        )
        turn = AssistantTurn.create(
            id=turn_id,
            organization_id=self.actor.organization_id,
            conversation_id=self.conversation.id,
            user_message_id=message_id,
            actor_membership_id=self.actor.membership_id,
            objective=values["message"],
            locale=values["locale"],
            now=now,
        )
        run = OrchestrationRun.create(
            id=run_id,
            organization_id=self.actor.organization_id,
            turn_id=turn_id,
            orchestrator_version="1.0.0",
            orchestrator_fingerprint="manifest",
            execution_plan={"steps": []},
            budget={"max_iterations": 8},
            now=now,
        )
        job = AssistantJob.create(
            organization_id=self.actor.organization_id,
            conversation_id=self.conversation.id,
            turn_id=turn_id,
            orchestration_run_id=run_id,
            requester_membership_id=self.actor.membership_id,
            payload={"turn_id": str(turn_id)},
            now=now,
        )
        event = AssistantEvent(
            id=uuid4(),
            organization_id=self.actor.organization_id,
            conversation_id=self.conversation.id,
            sequence=1,
            event_type="assistant.turn.queued.v1",
            public_payload={"status": "QUEUED"},
            turn_id=turn_id,
            orchestration_run_id=run_id,
            occurred_at=now,
        )
        return AssistantTurnMutationResult(message, turn, run, job, event, False)


class StubEventService:
    async def authorize(self, **_: Any) -> None:
        return None

    async def stream(self, **_: Any):  # type: ignore[no-untyped-def]
        yield ": heartbeat\n\n"


def _app(actor: AuthenticatedActor, service: StubAssistantService) -> FastAPI:
    event_service = StubEventService()
    app = create_app(
        Settings(environment="test"),
        assistant_service=service,  # type: ignore[arg-type]
        assistant_event_service=event_service,  # type: ignore[arg-type]
    )

    async def override_actor() -> AuthenticatedActor:
        return actor

    async def override_service() -> StubAssistantService:
        return service

    async def override_event_service() -> StubEventService:
        return event_service

    app.dependency_overrides[get_authenticated_actor] = override_actor
    app.dependency_overrides[get_assistant_service] = override_service
    app.dependency_overrides[get_assistant_event_service] = override_event_service
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [MembershipRole.ADMIN, MembershipRole.MANAGER, MembershipRole.EMPLOYEE]
)
async def test_all_roles_create_list_open_and_post_conversation(role: MembershipRole) -> None:
    actor = _actor(role)
    service = StubAssistantService(actor)
    transport = ASGITransport(app=_app(actor, service))
    headers = {"Idempotency-Key": "assistant-api-key-0001"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/ai/conversations",
            json={"locale": "en", "title": "My work"},
            headers=headers,
        )
        listed = await client.get("/api/v1/ai/conversations")
        opened = await client.get(f"/api/v1/ai/conversations/{service.conversation.id}")
        accepted = await client.post(
            f"/api/v1/ai/conversations/{service.conversation.id}/messages",
            json={"message": "What should I do?", "locale": "en"},
            headers=headers,
        )
        events = await client.get(
            f"/api/v1/ai/conversations/{service.conversation.id}/events",
            headers={"Last-Event-ID": "1"},
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert opened.status_code == 200
    assert opened.json()["messages"][0]["content_blocks"][0]["kind"] == "safe_error"
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "QUEUED"
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert events.text == ": heartbeat\n\n"


@pytest.mark.asyncio
async def test_revision_if_match_and_stale_error_are_structured() -> None:
    actor = _actor(MembershipRole.MANAGER)
    service = StubAssistantService(actor)
    service.error = AssistantServiceError("RESOURCE_VERSION_MISMATCH")
    transport = ASGITransport(app=_app(actor, service))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/v1/ai/conversations/{service.conversation.id}/messages",
            json={
                "message": "Revise it",
                "locale": "en",
                "card_action": {
                    "kind": "PLANNING_REVISE",
                    "workflow_run_id": str(uuid4()),
                    "proposal_id": str(uuid4()),
                },
            },
            headers={
                "Idempotency-Key": "assistant-stale-key-01",
                "If-Match": '"3"',
            },
        )

    assert response.status_code == 412
    assert response.json()["error"]["code"] == "RESOURCE_VERSION_MISMATCH"


@pytest.mark.asyncio
async def test_required_headers_strict_body_and_invalid_if_match_are_structured() -> None:
    actor = _actor()
    service = StubAssistantService(actor)
    transport = ASGITransport(app=_app(actor, service))
    url = f"/api/v1/ai/conversations/{service.conversation.id}/messages"
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing_key = await client.post(
            url,
            json={"message": "Hello", "locale": "en"},
        )
        extra_field = await client.post(
            url,
            json={"message": "Hello", "locale": "en", "agent_id": "planning"},
            headers={"Idempotency-Key": "assistant-extra-key-01"},
        )
        invalid_if_match = await client.post(
            url,
            json={
                "message": "Revise",
                "locale": "en",
                "card_action": {
                    "kind": "PLANNING_REVISE",
                    "workflow_run_id": str(uuid4()),
                    "proposal_id": str(uuid4()),
                },
            },
            headers={
                "Idempotency-Key": "assistant-invalid-etag",
                "If-Match": "3",
            },
        )

    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "VALIDATION_FAILED"
    assert extra_field.status_code == 422
    assert extra_field.json()["error"]["code"] == "VALIDATION_FAILED"
    assert invalid_if_match.status_code == 400
    assert invalid_if_match.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_non_disclosure_precondition_and_unsafe_exception_mapping() -> None:
    actor = _actor(MembershipRole.MANAGER)
    service = StubAssistantService(actor)
    transport = ASGITransport(app=_app(actor, service), raise_app_exceptions=False)
    url = f"/api/v1/ai/conversations/{service.conversation.id}/messages"
    payload = {
        "message": "Revise",
        "locale": "en",
        "card_action": {
            "kind": "PLANNING_REVISE",
            "workflow_run_id": str(uuid4()),
            "proposal_id": str(uuid4()),
        },
    }
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        service.error = ResourceNotFoundError()
        hidden = await client.get(f"/api/v1/ai/conversations/{uuid4()}")
        service.error = AssistantServiceError("IF_MATCH_REQUIRED")
        missing_version = await client.post(
            url,
            json=payload,
            headers={"Idempotency-Key": "assistant-missing-etag"},
        )
        service.error = RuntimeError("SQL secret prompt provider traceback")
        unsafe = await client.post(
            url,
            json=payload,
            headers={
                "Idempotency-Key": "assistant-unsafe-key-1",
                "If-Match": '"2"',
            },
        )

    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert missing_version.status_code == 428
    assert missing_version.json()["error"]["code"] == "PRECONDITION_REQUIRED"
    assert unsafe.status_code == 500
    assert unsafe.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in unsafe.text.casefold()
    assert "provider" not in unsafe.text.casefold()


def test_openapi_exposes_exact_paths_headers_and_discriminated_blocks() -> None:
    actor = _actor()
    schema = _app(actor, StubAssistantService(actor)).openapi()
    paths = schema["paths"]
    expected = {
        "/api/v1/ai/conversations",
        "/api/v1/ai/conversations/{conversation_id}",
        "/api/v1/ai/conversations/{conversation_id}/messages",
        "/api/v1/ai/conversations/{conversation_id}/events",
    }
    assert paths.keys() >= expected
    post = paths["/api/v1/ai/conversations/{conversation_id}/messages"]["post"]
    assert {p["name"] for p in post["parameters"] if p["in"] == "header"} == {
        "Idempotency-Key",
        "If-Match",
    }
    blocks = schema["components"]["schemas"]["MessageResponse"]["properties"]["content_blocks"][
        "items"
    ]
    assert blocks["discriminator"]["propertyName"] == "kind"
