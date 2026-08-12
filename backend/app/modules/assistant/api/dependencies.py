"""FastAPI dependency injection for AssistantService and AssistantEventService."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.modules.assistant.application.event_service import AssistantEventService
from app.modules.assistant.application.service import AssistantService


def get_assistant_service(request: Request) -> AssistantService:
    return cast(AssistantService, request.app.state.assistant_service)


def get_assistant_event_service(request: Request) -> AssistantEventService:
    return cast(AssistantEventService, request.app.state.assistant_event_service)


AssistantServiceDependency = Annotated[AssistantService, Depends(get_assistant_service)]
AssistantEventServiceDependency = Annotated[
    AssistantEventService, Depends(get_assistant_event_service)
]
