"""Versioned Task CRUD, status and My Tasks endpoints."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi import status as http_status

from app.api.errors import ApplicationError, ErrorResponse
from app.modules.identity.api.dependencies import ActorDependency
from app.modules.work.api.task_dependencies import TaskServiceDependency
from app.modules.work.api.task_schemas import (
    TaskCreateRequest,
    TaskPageResponse,
    TaskResponse,
    TaskStatusRequest,
    TaskUpdateRequest,
)
from app.modules.work.domain.tasks import (
    EmptyTaskPatchError,
    InvalidStatusTransitionError,
    InvalidTaskFieldError,
    TaskError,
    TaskForbiddenError,
    TaskIdempotencyKeyReusedError,
    TaskNotFoundError,
    TaskReferenceError,
    TaskStatus,
    TaskVersionMismatchError,
)

router = APIRouter(tags=["tasks"])
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


def _raise(error: TaskError) -> NoReturn:
    if isinstance(error, TaskForbiddenError):
        mapped = ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        )
    elif isinstance(error, TaskNotFoundError):
        mapped = ApplicationError(
            status_code=404, code="RESOURCE_NOT_FOUND", message_key="common.error.notFound"
        )
    elif isinstance(error, TaskVersionMismatchError):
        mapped = ApplicationError(
            status_code=412,
            code="RESOURCE_VERSION_MISMATCH",
            message_key="common.error.resourceVersionMismatch",
            details={"current_version": error.current_version},
        )
    elif isinstance(error, InvalidStatusTransitionError):
        mapped = ApplicationError(
            status_code=409,
            code="INVALID_STATUS_TRANSITION",
            message_key="task.error.invalidStatusTransition",
        )
    elif isinstance(error, TaskIdempotencyKeyReusedError):
        mapped = ApplicationError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message_key="common.error.idempotencyKeyReused",
        )
    elif isinstance(error, (InvalidTaskFieldError, EmptyTaskPatchError, TaskReferenceError)):
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


@router.get("/tasks", response_model=TaskPageResponse, responses=_ERRORS)
async def list_tasks(
    actor: ActorDependency,
    service: TaskServiceDependency,
    project_id: UUID | None = None,
    assignee_membership_id: UUID | None = None,
    status: TaskStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TaskPageResponse:
    return TaskPageResponse.from_domain(
        await service.list_tasks(
            actor=actor,
            project_id=project_id,
            assignee_membership_id=assignee_membership_id,
            status=status,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/my-tasks", response_model=TaskPageResponse, responses=_ERRORS)
async def my_tasks(
    actor: ActorDependency,
    service: TaskServiceDependency,
    status: TaskStatus | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TaskPageResponse:
    return TaskPageResponse.from_domain(
        await service.my_tasks(
            actor=actor,
            status=status,
            due_from=due_from,
            due_to=due_to,
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_task(
    payload: TaskCreateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: TaskServiceDependency,
    idempotency_key: IdempotencyKey,
) -> TaskResponse:
    try:
        result = await service.create_task(
            actor=actor,
            project_id=payload.project_id,
            title=payload.title,
            description=payload.description,
            assignee_membership_id=payload.assignee_membership_id,
            due_date=payload.due_date,
            milestone_id=payload.milestone_id,
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except TaskError as error:
        _raise(error)
    _headers(response, result.task.version, result.replayed)
    return TaskResponse.from_domain(result.task)


@router.get("/tasks/{task_id}", response_model=TaskResponse, responses=_ERRORS)
async def get_task(
    task_id: UUID, actor: ActorDependency, service: TaskServiceDependency, response: Response
) -> TaskResponse:
    try:
        task = await service.get_task(actor=actor, task_id=task_id)
    except TaskError as error:
        _raise(error)
    response.headers["ETag"] = f'"{task.version}"'
    return TaskResponse.from_domain(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse, responses=_ERRORS)
async def update_task(
    task_id: UUID,
    payload: TaskUpdateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: TaskServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> TaskResponse:
    supplied = payload.model_fields_set
    try:
        result = await service.update_task(
            actor=actor,
            task_id=task_id,
            title=payload.title,
            title_supplied="title" in supplied,
            description=payload.description,
            description_supplied="description" in supplied,
            assignee_membership_id=payload.assignee_membership_id,
            assignee_supplied="assignee_membership_id" in supplied,
            due_date=payload.due_date,
            due_date_supplied="due_date" in supplied,
            milestone_id=payload.milestone_id,
            milestone_supplied="milestone_id" in supplied,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except TaskError as error:
        _raise(error)
    _headers(response, result.task.version, result.replayed)
    return TaskResponse.from_domain(result.task)


@router.post("/tasks/{task_id}/status", response_model=TaskResponse, responses=_ERRORS)
async def transition_task(
    task_id: UUID,
    payload: TaskStatusRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: TaskServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> TaskResponse:
    try:
        result = await service.transition_task(
            actor=actor,
            task_id=task_id,
            target=payload.to_status,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except TaskError as error:
        _raise(error)
    _headers(response, result.task.version, result.replayed)
    return TaskResponse.from_domain(result.task)
