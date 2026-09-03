"""People Capacity service dependency."""

from functools import partial
from inspect import isawaitable
from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.errors import ApplicationError
from app.core.config import Settings
from app.modules.identity.api.dependencies import get_authenticated_actor
from app.modules.identity.application.auth_service import AuthService
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.people_capacity.application.service import PeopleCapacityService
from app.modules.people_capacity.domain.skills import PeopleSkillForbiddenError


def get_people_capacity_service(request: Request) -> PeopleCapacityService:
    return cast(PeopleCapacityService, request.app.state.people_capacity_service)


PeopleCapacityServiceDependency = Annotated[
    PeopleCapacityService, Depends(get_people_capacity_service)
]

_ACTIONS = {
    "create_skill": "people.skill.created",
    "update_skill": "people.skill.updated",
    "delete_skill": "people.skill.deleted",
    "set_person_skill": "people.person_skill.upserted",
    "delete_person_skill": "people.person_skill.deleted",
    "record_work_outcome_evidence": "people.work_outcome_evidence.created",
}


def _audit_idempotency_key(request: Request) -> str | None:
    value = request.headers.get("Idempotency-Key")
    return value if value is not None and len(value) <= 128 else None


async def prepare_people_mutation(request: Request, *, route_name: str) -> None:
    """Authorize and install rejection auditing before FastAPI parses the body."""
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
    service = cast(PeopleCapacityService, request.app.state.people_capacity_service)
    action = _ACTIONS.get(route_name, "people.mutation.rejected")
    idempotency_key = _audit_idempotency_key(request)
    try:
        await service.authorize_mutation(
            actor=actor,
            action=action,
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except PeopleSkillForbiddenError as error:
        raise ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        ) from error
    request.state.mutation_rejection_audit = partial(
        service.audit_transport_rejection,
        actor=actor,
        action=action,
        request_id=str(request.state.request_id),
        idempotency_key=idempotency_key,
    )
    request.state.people_mutation_actor = actor


def get_people_mutation_actor(request: Request) -> AuthenticatedActor:
    actor = getattr(request.state, "people_mutation_actor", None)
    if not isinstance(actor, AuthenticatedActor):
        raise RuntimeError("People mutation preflight did not resolve an actor")
    return actor


PeopleMutationActorDependency = Annotated[AuthenticatedActor, Depends(get_people_mutation_actor)]
