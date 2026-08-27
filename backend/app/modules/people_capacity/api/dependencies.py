"""People Capacity service dependency."""

from typing import Annotated, cast

from fastapi import Depends, Header, Request

from app.api.errors import ApplicationError
from app.modules.identity.api.dependencies import ActorDependency
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


async def get_people_mutation_actor(
    request: Request,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AuthenticatedActor:
    route_name = str(getattr(request.scope.get("route"), "name", "people_mutation"))
    try:
        await service.authorize_mutation(
            actor=actor,
            action=_ACTIONS.get(route_name, "people.mutation.rejected"),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except PeopleSkillForbiddenError as error:
        raise ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        ) from error
    return actor


PeopleMutationActorDependency = Annotated[AuthenticatedActor, Depends(get_people_mutation_actor)]
