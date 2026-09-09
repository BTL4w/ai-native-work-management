"""Team Requirement service dependency."""

from functools import partial
from inspect import isawaitable
from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.errors import ApplicationError
from app.core.config import Settings
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.application.auth_service import AuthService
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.assignment.application.requirement_service import (
    TeamRequirementService,
)


def get_team_requirement_service(request: Request) -> TeamRequirementService:
    return cast(TeamRequirementService, request.app.state.team_requirement_service)


TeamRequirementServiceDependency = Annotated[
    TeamRequirementService, Depends(get_team_requirement_service)
]


async def prepare_requirement_mutation(request: Request) -> None:
    """Resolve authorization and audit before even malformed JSON is decoded."""
    override = request.app.dependency_overrides.get(get_authenticated_actor)
    if override is not None:
        candidate = override()
        actor = await candidate if isawaitable(candidate) else candidate
    else:
        actor = await get_authenticated_actor(
            request,
            cast(AuthService, request.app.state.auth_service),
            cast(Settings, request.app.state.settings),
        )
    service = get_team_requirement_service(request)
    key = request.headers.get("Idempotency-Key")
    action = "derive" if request.method == "POST" else "patch"
    request.state.mutation_rejection_audit = partial(
        service.audit_transport_rejection,
        actor=actor,
        action=f"team_requirement.{action}.rejected",
        request_id=str(request.state.request_id),
        idempotency_key=key if key is not None and len(key) <= 128 else None,
    )
    if actor.role not in {MembershipRole.ADMIN, MembershipRole.MANAGER}:
        raise ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        )
    request.state.requirement_mutation_actor = actor


def get_requirement_mutation_actor(request: Request) -> AuthenticatedActor:
    return cast(AuthenticatedActor, request.state.requirement_mutation_actor)


RequirementMutationActorDependency = Annotated[
    AuthenticatedActor, Depends(get_requirement_mutation_actor)
]
