"""Versioned Project REST endpoints."""

from __future__ import annotations

import re
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.api.errors import ApplicationError, ErrorResponse
from app.modules.identity.api.dependencies import ActorDependency
from app.modules.work.api.dependencies import ProjectServiceDependency
from app.modules.work.api.schemas import (
    ProjectCreateRequest,
    ProjectPageResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.modules.work.domain.projects import (
    EmptyProjectPatchError,
    IdempotencyKeyReusedError,
    InvalidProjectFieldError,
    ProjectError,
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectVersionMismatchError,
)

router = APIRouter(prefix="/projects", tags=["projects"])

IdempotencyKeyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
]
IfMatchHeader = Annotated[str | None, Header(alias="If-Match")]

_VERSION_ETAG = re.compile(r'^"([1-9][0-9]*)"$')
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 412, 422, 428)
}


def _expected_version(value: str | None) -> int:
    if value is None:
        raise ApplicationError(
            status_code=428,
            code="PRECONDITION_REQUIRED",
            message_key="common.error.preconditionRequired",
        )
    match = _VERSION_ETAG.fullmatch(value)
    if match is None:
        raise ApplicationError(
            status_code=400,
            code="INVALID_REQUEST",
            message_key="common.error.invalidRequest",
        )
    return int(match.group(1))


def _raise_project_error(error: Exception) -> NoReturn:
    if isinstance(error, ProjectForbiddenError):
        mapped = ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        )
    elif isinstance(error, ProjectNotFoundError):
        mapped = ApplicationError(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message_key="common.error.notFound",
        )
    elif isinstance(error, ProjectVersionMismatchError):
        mapped = ApplicationError(
            status_code=412,
            code="RESOURCE_VERSION_MISMATCH",
            message_key="common.error.resourceVersionMismatch",
            details={"current_version": error.current_version},
        )
    elif isinstance(error, IdempotencyKeyReusedError):
        mapped = ApplicationError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message_key="common.error.idempotencyKeyReused",
        )
    elif isinstance(error, (InvalidProjectFieldError, EmptyProjectPatchError)):
        mapped = ApplicationError(
            status_code=422,
            code="VALIDATION_FAILED",
            message_key="common.error.validation",
        )
    else:
        raise error
    raise mapped from error


def _set_mutation_headers(response: Response, *, version: int, replayed: bool) -> None:
    response.headers["ETag"] = f'"{version}"'
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"


@router.get("", response_model=ProjectPageResponse, responses=_ERROR_RESPONSES)
async def list_projects(
    actor: ActorDependency,
    service: ProjectServiceDependency,
    q: Annotated[str | None, Query(max_length=160)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProjectPageResponse:
    result = await service.list_projects(actor=actor, query=q, page=page, page_size=page_size)
    return ProjectPageResponse.from_domain(result)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
)
async def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ProjectServiceDependency,
    idempotency_key: IdempotencyKeyHeader,
) -> ProjectResponse:
    try:
        result = await service.create_project(
            actor=actor,
            name=payload.name,
            description=payload.description,
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except ProjectError as error:
        _raise_project_error(error)
    _set_mutation_headers(response, version=result.project.version, replayed=result.replayed)
    return ProjectResponse.from_domain(result.project)


@router.get("/{project_id}", response_model=ProjectResponse, responses=_ERROR_RESPONSES)
async def get_project(
    project_id: UUID,
    actor: ActorDependency,
    service: ProjectServiceDependency,
    response: Response,
) -> ProjectResponse:
    try:
        project = await service.get_project(actor=actor, project_id=project_id)
    except ProjectError as error:
        _raise_project_error(error)
    response.headers["ETag"] = f'"{project.version}"'
    return ProjectResponse.from_domain(project)


@router.patch("/{project_id}", response_model=ProjectResponse, responses=_ERROR_RESPONSES)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ProjectServiceDependency,
    idempotency_key: IdempotencyKeyHeader,
    if_match: IfMatchHeader = None,
) -> ProjectResponse:
    try:
        result = await service.update_project(
            actor=actor,
            project_id=project_id,
            name=payload.name,
            name_supplied="name" in payload.model_fields_set,
            description=payload.description,
            description_supplied="description" in payload.model_fields_set,
            expected_version=_expected_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except ProjectError as error:
        _raise_project_error(error)
    _set_mutation_headers(response, version=result.project.version, replayed=result.replayed)
    return ProjectResponse.from_domain(result.project)
