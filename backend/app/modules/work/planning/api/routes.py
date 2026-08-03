"""Versioned manual planning CRUD endpoints."""

from __future__ import annotations

import re
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi import status as http_status

from app.api.errors import ApplicationError, ErrorResponse
from app.modules.identity.api.dependencies import ActorDependency
from app.modules.work.planning.api.dependencies import ManualPlanningServiceDependency
from app.modules.work.planning.api.schemas import (
    AcceptanceCriterionCreateRequest,
    AcceptanceCriterionResponse,
    AcceptanceCriterionUpdateRequest,
    DeleteResponse,
    DependencyCreateRequest,
    DependencyResponse,
    DependencyUpdateRequest,
    GoalCreateRequest,
    GoalResponse,
    GoalUpdateRequest,
    MilestoneCreateRequest,
    MilestoneResponse,
    MilestoneUpdateRequest,
    PlanningPageResponse,
)
from app.modules.work.planning.application.manual_service import (
    PlanningError,
    PlanningForbiddenError,
    PlanningIdempotencyKeyReusedError,
    PlanningNotFoundError,
    PlanningReferenceError,
    PlanningVersionMismatchError,
)
from app.modules.work.planning.domain.acceptance_criteria import AcceptanceCriterionError
from app.modules.work.planning.domain.dependencies import DependencyError
from app.modules.work.planning.domain.goals import GoalError
from app.modules.work.planning.domain.milestones import MilestoneError

router = APIRouter(tags=["planning"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
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
    if isinstance(error, PlanningForbiddenError):
        mapped = ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        )
    elif isinstance(error, PlanningNotFoundError):
        mapped = ApplicationError(
            status_code=404, code="RESOURCE_NOT_FOUND", message_key="common.error.notFound"
        )
    elif isinstance(error, PlanningVersionMismatchError):
        mapped = ApplicationError(
            status_code=412,
            code="RESOURCE_VERSION_MISMATCH",
            message_key="common.error.resourceVersionMismatch",
            details={"current_version": error.current_version},
        )
    elif isinstance(error, PlanningIdempotencyKeyReusedError):
        mapped = ApplicationError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message_key="common.error.idempotencyKeyReused",
        )
    elif isinstance(
        error,
        (
            PlanningReferenceError,
            PlanningError,
            GoalError,
            MilestoneError,
            DependencyError,
            AcceptanceCriterionError,
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


@router.get("/goals", response_model=PlanningPageResponse, responses=_ERRORS)
async def list_goals(
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    project_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> PlanningPageResponse:
    return PlanningPageResponse.goals(
        await service.list_goals(actor=actor, project_id=project_id, page=page, page_size=page_size)
    )


@router.post(
    "/goals",
    response_model=GoalResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_goal(
    payload: GoalCreateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
) -> GoalResponse:
    try:
        result = await service.create_goal(
            actor=actor,
            project_id=payload.project_id,
            title=payload.title,
            description=payload.description,
            expected_outcomes=tuple(payload.expected_outcomes),
            target_date=payload.target_date,
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    assert hasattr(result.resource, "title")
    _headers(response, result.resource.version, result.replayed)
    return GoalResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.get("/goals/{goal_id}", response_model=GoalResponse, responses=_ERRORS)
async def get_goal(
    goal_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
) -> GoalResponse:
    try:
        resource = await service.get_goal(actor=actor, goal_id=goal_id)
    except Exception as error:
        _raise(error)
    response.headers["ETag"] = f'"{resource.version}"'
    return GoalResponse.from_domain(resource)


@router.patch("/goals/{goal_id}", response_model=GoalResponse, responses=_ERRORS)
async def update_goal(
    goal_id: UUID,
    payload: GoalUpdateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> GoalResponse:
    supplied = payload.model_fields_set
    try:
        result = await service.update_goal(
            actor=actor,
            goal_id=goal_id,
            title=payload.title,
            title_supplied="title" in supplied,
            description=payload.description,
            description_supplied="description" in supplied,
            expected_outcomes=tuple(payload.expected_outcomes or ()),
            expected_outcomes_supplied="expected_outcomes" in supplied,
            target_date=payload.target_date,
            target_date_supplied="target_date" in supplied,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.resource.version, result.replayed)
    return GoalResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.delete("/goals/{goal_id}", response_model=DeleteResponse, responses=_ERRORS)
async def delete_goal(
    goal_id: UUID,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> DeleteResponse:
    try:
        result = await service.delete_goal(
            actor=actor,
            goal_id=goal_id,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.version, result.replayed)
    return DeleteResponse.from_domain(result)


@router.get("/milestones", response_model=PlanningPageResponse, responses=_ERRORS)
async def list_milestones(
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    project_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> PlanningPageResponse:
    return PlanningPageResponse.milestones(
        await service.list_milestones(
            actor=actor, project_id=project_id, page=page, page_size=page_size
        )
    )


@router.post(
    "/milestones",
    response_model=MilestoneResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_milestone(
    payload: MilestoneCreateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
) -> MilestoneResponse:
    try:
        result = await service.create_milestone(
            actor=actor,
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            target_date=payload.target_date,
            position=payload.position,
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.resource.version, result.replayed)
    return MilestoneResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.get("/milestones/{milestone_id}", response_model=MilestoneResponse, responses=_ERRORS)
async def get_milestone(
    milestone_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
) -> MilestoneResponse:
    try:
        resource = await service.get_milestone(actor=actor, milestone_id=milestone_id)
    except Exception as error:
        _raise(error)
    response.headers["ETag"] = f'"{resource.version}"'
    return MilestoneResponse.from_domain(resource)


@router.patch("/milestones/{milestone_id}", response_model=MilestoneResponse, responses=_ERRORS)
async def update_milestone(
    milestone_id: UUID,
    payload: MilestoneUpdateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> MilestoneResponse:
    supplied = payload.model_fields_set
    try:
        result = await service.update_milestone(
            actor=actor,
            milestone_id=milestone_id,
            name=payload.name,
            name_supplied="name" in supplied,
            description=payload.description,
            description_supplied="description" in supplied,
            target_date=payload.target_date,
            target_date_supplied="target_date" in supplied,
            position=payload.position,
            position_supplied="position" in supplied,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.resource.version, result.replayed)
    return MilestoneResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.delete("/milestones/{milestone_id}", response_model=DeleteResponse, responses=_ERRORS)
async def delete_milestone(
    milestone_id: UUID,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> DeleteResponse:
    try:
        result = await service.delete_milestone(
            actor=actor,
            milestone_id=milestone_id,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.version, result.replayed)
    return DeleteResponse.from_domain(result)


@router.get("/task-dependencies", response_model=PlanningPageResponse, responses=_ERRORS)
async def list_dependencies(
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> PlanningPageResponse:
    return PlanningPageResponse.dependencies(
        await service.list_dependencies(
            actor=actor, project_id=project_id, task_id=task_id, page=page, page_size=page_size
        )
    )


@router.post(
    "/task-dependencies",
    response_model=DependencyResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_dependency(
    payload: DependencyCreateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
) -> DependencyResponse:
    try:
        result = await service.create_dependency(
            actor=actor,
            predecessor_task_id=payload.predecessor_task_id,
            successor_task_id=payload.successor_task_id,
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.resource.version, result.replayed)
    return DependencyResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.get(
    "/task-dependencies/{dependency_id}", response_model=DependencyResponse, responses=_ERRORS
)
async def get_dependency(
    dependency_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
) -> DependencyResponse:
    try:
        resource = await service.get_dependency(actor=actor, dependency_id=dependency_id)
    except Exception as error:
        _raise(error)
    response.headers["ETag"] = f'"{resource.version}"'
    return DependencyResponse.from_domain(resource)


@router.patch(
    "/task-dependencies/{dependency_id}", response_model=DependencyResponse, responses=_ERRORS
)
async def update_dependency(
    dependency_id: UUID,
    payload: DependencyUpdateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> DependencyResponse:
    supplied = payload.model_fields_set
    try:
        result = await service.update_dependency(
            actor=actor,
            dependency_id=dependency_id,
            predecessor_task_id=payload.predecessor_task_id,
            predecessor_supplied="predecessor_task_id" in supplied,
            successor_task_id=payload.successor_task_id,
            successor_supplied="successor_task_id" in supplied,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.resource.version, result.replayed)
    return DependencyResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.delete(
    "/task-dependencies/{dependency_id}", response_model=DeleteResponse, responses=_ERRORS
)
async def delete_dependency(
    dependency_id: UUID,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> DeleteResponse:
    try:
        result = await service.delete_dependency(
            actor=actor,
            dependency_id=dependency_id,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.version, result.replayed)
    return DeleteResponse.from_domain(result)


@router.get("/acceptance-criteria", response_model=PlanningPageResponse, responses=_ERRORS)
async def list_criteria(
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    task_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> PlanningPageResponse:
    return PlanningPageResponse.criteria(
        await service.list_acceptance_criteria(
            actor=actor, task_id=task_id, page=page, page_size=page_size
        )
    )


@router.post(
    "/acceptance-criteria",
    response_model=AcceptanceCriterionResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_criterion(
    payload: AcceptanceCriterionCreateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
) -> AcceptanceCriterionResponse:
    try:
        result = await service.create_acceptance_criterion(
            actor=actor,
            task_id=payload.task_id,
            text=payload.text,
            position=payload.position,
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.resource.version, result.replayed)
    return AcceptanceCriterionResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.get(
    "/acceptance-criteria/{criterion_id}",
    response_model=AcceptanceCriterionResponse,
    responses=_ERRORS,
)
async def get_criterion(
    criterion_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
) -> AcceptanceCriterionResponse:
    try:
        resource = await service.get_acceptance_criterion(actor=actor, criterion_id=criterion_id)
    except Exception as error:
        _raise(error)
    response.headers["ETag"] = f'"{resource.version}"'
    return AcceptanceCriterionResponse.from_domain(resource)


@router.patch(
    "/acceptance-criteria/{criterion_id}",
    response_model=AcceptanceCriterionResponse,
    responses=_ERRORS,
)
async def update_criterion(
    criterion_id: UUID,
    payload: AcceptanceCriterionUpdateRequest,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> AcceptanceCriterionResponse:
    supplied = payload.model_fields_set
    try:
        result = await service.update_acceptance_criterion(
            actor=actor,
            criterion_id=criterion_id,
            text=payload.text,
            text_supplied="text" in supplied,
            position=payload.position,
            position_supplied="position" in supplied,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.resource.version, result.replayed)
    return AcceptanceCriterionResponse.from_domain(result.resource)  # type: ignore[arg-type]


@router.delete(
    "/acceptance-criteria/{criterion_id}", response_model=DeleteResponse, responses=_ERRORS
)
async def delete_criterion(
    criterion_id: UUID,
    request: Request,
    response: Response,
    actor: ActorDependency,
    service: ManualPlanningServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> DeleteResponse:
    try:
        result = await service.delete_acceptance_criterion(
            actor=actor,
            criterion_id=criterion_id,
            expected_version=_version(if_match),
            request_id=str(request.state.request_id),
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, result.version, result.replayed)
    return DeleteResponse.from_domain(result)
