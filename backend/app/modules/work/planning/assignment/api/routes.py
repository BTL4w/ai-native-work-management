"""Optimistic-concurrency API for one Project's Team Requirement snapshot."""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Body, Header, Request, Response, status
from fastapi.routing import APIRoute

from app.api.errors import ApplicationError, ErrorResponse
from app.modules.identity.api.dependencies import ActorDependency
from app.modules.people_capacity.domain.skills import SkillLevel
from app.modules.work.planning.assignment.api.dependencies import (
    RequirementMutationActorDependency,
    TeamRequirementServiceDependency,
    prepare_requirement_mutation,
)
from app.modules.work.planning.assignment.api.schemas import (
    TeamRequirementSetResponse,
    TeamRequirementsPatchRequest,
)
from app.modules.work.planning.assignment.application.requirement_service import (
    ConfirmRequirementsCommand,
    DeriveRequirementsCommand,
    GetRequirementsQuery,
    RequirementItemInput,
    ReviseRequirementsCommand,
    TeamRequirementError,
    TeamRequirementForbiddenError,
    TeamRequirementIdempotencyKeyReusedError,
    TeamRequirementIncompleteError,
    TeamRequirementNotFoundError,
    TeamRequirementReferenceError,
    TeamRequirementVersionMismatchError,
)


class TeamRequirementRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def preflight(request: Request) -> Response:
            if request.method in {"POST", "PATCH"}:
                await prepare_requirement_mutation(request)
            return await handler(request)

        return preflight


router = APIRouter(tags=["team-requirements"], route_class=TeamRequirementRoute)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
_ETAG = re.compile(r'^"([1-9][0-9]*)"$')
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 412, 422, 428)
}


def _version(value: str | None) -> int:
    if value is None:
        raise ApplicationError(
            status_code=428,
            code="PRECONDITION_REQUIRED",
            message_key="common.error.preconditionRequired",
        )
    match = _ETAG.fullmatch(value)
    if not match:
        raise ApplicationError(
            status_code=400, code="INVALID_REQUEST", message_key="common.error.invalidRequest"
        )
    return int(match.group(1))


def _raise(error: Exception) -> NoReturn:
    if isinstance(error, ApplicationError):
        raise error
    if isinstance(error, TeamRequirementForbiddenError):
        mapped = ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        )
    elif isinstance(error, TeamRequirementNotFoundError):
        mapped = ApplicationError(
            status_code=404, code="RESOURCE_NOT_FOUND", message_key="common.error.notFound"
        )
    elif isinstance(error, TeamRequirementVersionMismatchError):
        mapped = ApplicationError(
            status_code=412,
            code="RESOURCE_VERSION_MISMATCH",
            message_key="common.error.resourceVersionMismatch",
            details={"current_version": error.current_version},
        )
    elif isinstance(error, TeamRequirementIdempotencyKeyReusedError):
        mapped = ApplicationError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message_key="common.error.idempotencyKeyReused",
        )
    elif isinstance(
        error,
        (
            TeamRequirementIncompleteError,
            TeamRequirementReferenceError,
            TeamRequirementError,
        ),
    ):
        mapped = ApplicationError(
            status_code=422, code="VALIDATION_FAILED", message_key="common.error.validation"
        )
    else:
        raise error
    raise mapped from error


def _headers(response: Response, version: int, replayed: bool) -> None:
    response.headers["ETag"] = f'"{version}"'
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"


@router.get(
    "/projects/{project_id}/team-requirements",
    response_model=TeamRequirementSetResponse,
    responses=_ERRORS,
)
async def get_team_requirements(
    project_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: TeamRequirementServiceDependency,
) -> TeamRequirementSetResponse:
    try:
        result = await service.get_for_project(GetRequirementsQuery(actor, project_id))
    except Exception as error:
        _raise(error)
    _headers(response, result.version, result.replayed)
    return TeamRequirementSetResponse.from_domain(result)


@router.post(
    "/projects/{project_id}/team-requirements",
    response_model=TeamRequirementSetResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def derive_team_requirements(
    project_id: UUID,
    request: Request,
    response: Response,
    actor: RequirementMutationActorDependency,
    service: TeamRequirementServiceDependency,
    idempotency_key: IdempotencyKey,
    payload: None = Body(default=None),
) -> TeamRequirementSetResponse:
    del payload
    request.state.mutation_rejection_audit = None
    try:
        result = await service.derive(
            DeriveRequirementsCommand(
                actor, project_id, str(request.state.request_id), idempotency_key
            )
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.version, result.replayed)
    return TeamRequirementSetResponse.from_domain(result)


@router.patch(
    "/projects/{project_id}/team-requirements",
    response_model=TeamRequirementSetResponse,
    responses=_ERRORS,
)
async def patch_team_requirements(
    project_id: UUID,
    payload: TeamRequirementsPatchRequest,
    request: Request,
    response: Response,
    actor: RequirementMutationActorDependency,
    service: TeamRequirementServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> TeamRequirementSetResponse:
    request.state.mutation_rejection_audit = partial(
        service.audit_transport_rejection,
        actor=actor,
        action=f"team_requirement.{payload.action}.rejected",
        request_id=str(request.state.request_id),
        idempotency_key=idempotency_key,
    )
    expected = _version(if_match)
    try:
        current = await service.get_for_project(GetRequirementsQuery(actor, project_id))
        request.state.mutation_rejection_audit = None
        if payload.action == "confirm":
            result = await service.confirm(
                ConfirmRequirementsCommand(
                    actor,
                    project_id,
                    current.id,
                    expected,
                    str(request.state.request_id),
                    idempotency_key,
                )
            )
        else:
            items = tuple(
                RequirementItemInput(
                    item.skill_id,
                    SkillLevel(item.minimum_level),
                    item.project_week_id,
                    item.effort_hours,
                    item.source_task_ids,
                )
                for item in payload.items
            )
            incomplete = tuple((item.task_id, item.reason) for item in payload.incomplete_items)
            result = await service.revise(
                ReviseRequirementsCommand(
                    actor,
                    project_id,
                    current.id,
                    expected,
                    str(request.state.request_id),
                    idempotency_key,
                    items,
                    incomplete,
                )
            )
    except Exception as error:
        _raise(error)
    _headers(response, result.version, result.replayed)
    return TeamRequirementSetResponse.from_domain(result)
