"""Manager lifecycle API with pre-parse authorization and rejection auditing."""

import re
from collections.abc import Callable, Coroutine
from functools import partial
from inspect import isawaitable
from typing import Annotated, Any, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from fastapi.routing import APIRoute

from app.api.errors import ApplicationError, ErrorResponse
from app.core.config import Settings
from app.modules.identity.api.dependencies import ActorDependency, get_authenticated_actor
from app.modules.identity.application.auth_service import AuthService
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.work.planning.assignment.api.recommendation_schemas import (
    CreateRecommendationRequest,
    DecideRecommendationRequest,
    ProjectTeamMembershipResponse,
    ProjectTeamResponse,
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
    RecommendationVersionResponse,
    ReviseRecommendationRequest,
)
from app.modules.work.planning.assignment.application.recommendation_service import (
    CreateRecommendationCommand,
    DecideRecommendationCommand,
    RecordFeedbackCommand,
    ReviseRecommendationCommand,
    TeamRecommendationService,
)
from app.modules.work.planning.assignment.domain.recommendations import (
    CandidateOverride,
    RecommendationError,
)


def get_team_recommendation_service(request: Request) -> TeamRecommendationService:
    return cast(TeamRecommendationService, request.app.state.team_recommendation_service)


Service = Annotated[TeamRecommendationService, Depends(get_team_recommendation_service)]


def mutation_actor(request: Request) -> AuthenticatedActor:
    return cast(AuthenticatedActor, request.state.recommendation_actor)


MutationActor = Annotated[AuthenticatedActor, Depends(mutation_actor)]


class RecommendationRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def preflight(request: Request) -> Response:
            if request.method in {"POST", "PATCH"}:
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
                service = get_team_recommendation_service(request)
                key = request.headers.get("Idempotency-Key")
                request.state.mutation_rejection_audit = partial(
                    service.audit_transport_rejection,
                    actor=actor,
                    action="team_recommendation.transport.rejected",
                    request_id=str(request.state.request_id),
                    idempotency_key=key if key and len(key) <= 128 else None,
                )
                if actor.role not in {MembershipRole.ADMIN, MembershipRole.MANAGER}:
                    raise ApplicationError(
                        status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
                    )
                request.state.recommendation_actor = actor
            return await handler(request)

        return preflight


router = APIRouter(tags=["team-recommendations"], route_class=RecommendationRoute)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
_ETAG = re.compile(r'^"([1-9][0-9]*)"$')
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 412, 422, 428)
}


def parse_version(value: str | None) -> int:
    if value is None:
        raise ApplicationError(
            status_code=428,
            code="PRECONDITION_REQUIRED",
            message_key="common.error.preconditionRequired",
        )
    match = _ETAG.fullmatch(value)
    if not match:
        raise ApplicationError(
            status_code=400,
            code="INVALID_REQUEST",
            message_key="common.error.invalidRequest",
        )
    return int(match.group(1))


def set_mutation_headers(response: Response, version: int, replayed: bool) -> None:
    response.headers["ETag"] = f'"{version}"'
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"


def _raise(error: RecommendationError) -> NoReturn:
    status = {
        "FORBIDDEN": 403,
        "RESOURCE_NOT_FOUND": 404,
        "RESOURCE_VERSION_MISMATCH": 412,
        "IDEMPOTENCY_KEY_REUSED": 409,
        "STALE_REQUIREMENTS": 409,
        "STALE_POLICY": 409,
        "RECOMMENDATION_NOT_PROPOSED": 409,
        "CONCURRENT_MODIFICATION": 409,
    }.get(error.code, 422)
    key = {403: "forbidden", 404: "notFound", 412: "resourceVersionMismatch", 409: "conflict"}.get(
        status, "validation"
    )
    raise ApplicationError(
        status_code=status,
        code=error.code,
        message_key="common.error." + key,
        details={"current_version": error.current_version} if error.current_version else {},
    ) from error


@router.get("/projects/{project_id}/team", response_model=ProjectTeamResponse, responses=_ERRORS)
async def get_project_team(
    project_id: UUID, actor: ActorDependency, service: Service
) -> ProjectTeamResponse:
    try:
        result = await service.team(actor, project_id)
    except RecommendationError as error:
        _raise(error)
    return ProjectTeamResponse(
        memberships=tuple(ProjectTeamMembershipResponse.model_validate(r) for r in result)
    )


@router.post(
    "/projects/{project_id}/team-recommendations",
    status_code=201,
    response_model=RecommendationVersionResponse,
    responses=_ERRORS,
)
async def create_recommendation(
    project_id: UUID,
    payload: CreateRecommendationRequest,
    request: Request,
    response: Response,
    actor: MutationActor,
    service: Service,
    idempotency_key: IdempotencyKey,
) -> RecommendationVersionResponse:
    request.state.mutation_rejection_audit = None
    try:
        result = await service.create(
            CreateRecommendationCommand(
                actor=actor,
                project_id=project_id,
                request_id=str(request.state.request_id),
                idempotency_key=idempotency_key,
                requirement_set_id=payload.requirement_set_id,
                requirement_version=payload.requirement_version,
                policy_version=payload.policy_version,
            )
        )
    except RecommendationError as error:
        _raise(error)
    set_mutation_headers(response, result.version, result.replayed)
    return RecommendationVersionResponse.model_validate(result)


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationVersionResponse,
    responses=_ERRORS,
)
async def get_recommendation(
    recommendation_id: UUID, response: Response, actor: ActorDependency, service: Service
) -> RecommendationVersionResponse:
    try:
        result = await service.get(actor, recommendation_id)
    except RecommendationError as error:
        _raise(error)
    set_mutation_headers(response, result.version, result.replayed)
    return RecommendationVersionResponse.model_validate(result)


@router.get(
    "/recommendations/{recommendation_id}/versions/{version}",
    response_model=RecommendationVersionResponse,
    responses=_ERRORS,
)
async def get_recommendation_version(
    recommendation_id: UUID,
    version: Annotated[int, Path(gt=0)],
    response: Response,
    actor: ActorDependency,
    service: Service,
) -> RecommendationVersionResponse:
    try:
        result = await service.get(actor, recommendation_id, version)
    except RecommendationError as error:
        _raise(error)
    set_mutation_headers(response, result.version, result.replayed)
    return RecommendationVersionResponse.model_validate(result)


@router.patch(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationVersionResponse,
    responses=_ERRORS,
)
async def revise_recommendation(
    recommendation_id: UUID,
    payload: ReviseRecommendationRequest,
    request: Request,
    response: Response,
    actor: MutationActor,
    service: Service,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> RecommendationVersionResponse:
    expected = parse_version(if_match)
    request.state.mutation_rejection_audit = None
    try:
        result = await service.revise(
            ReviseRecommendationCommand(
                actor=actor,
                request_id=str(request.state.request_id),
                idempotency_key=idempotency_key,
                recommendation_id=recommendation_id,
                expected_version=expected,
                overrides=tuple(
                    CandidateOverride(
                        r.requirement_id,
                        r.selected_membership_id,
                        r.override_reason,
                        r.allocated_effort_hours,
                    )
                    for r in payload.overrides
                ),
            )
        )
    except RecommendationError as error:
        _raise(error)
    set_mutation_headers(response, result.version, result.replayed)
    return RecommendationVersionResponse.model_validate(result)


@router.post(
    "/recommendations/{recommendation_id}/approve",
    response_model=RecommendationVersionResponse,
    responses=_ERRORS,
)
async def decide_recommendation(
    recommendation_id: UUID,
    payload: DecideRecommendationRequest,
    request: Request,
    response: Response,
    actor: MutationActor,
    service: Service,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> RecommendationVersionResponse:
    expected = parse_version(if_match)
    request.state.mutation_rejection_audit = None
    try:
        result = await service.decide(
            DecideRecommendationCommand(
                actor=actor,
                request_id=str(request.state.request_id),
                idempotency_key=idempotency_key,
                recommendation_id=recommendation_id,
                expected_version=expected,
                action=payload.action,
                reason=payload.reason,
            )
        )
    except RecommendationError as error:
        _raise(error)
    set_mutation_headers(response, result.version, result.replayed)
    return RecommendationVersionResponse.model_validate(result)


@router.post(
    "/recommendations/{recommendation_id}/feedback",
    status_code=201,
    response_model=RecommendationFeedbackResponse,
    responses=_ERRORS,
)
async def record_recommendation_feedback(
    recommendation_id: UUID,
    payload: RecommendationFeedbackRequest,
    request: Request,
    response: Response,
    actor: MutationActor,
    service: Service,
    idempotency_key: IdempotencyKey,
) -> RecommendationFeedbackResponse:
    request.state.mutation_rejection_audit = None
    try:
        result = await service.record_feedback(
            RecordFeedbackCommand(
                actor=actor,
                request_id=str(request.state.request_id),
                idempotency_key=idempotency_key,
                recommendation_id=recommendation_id,
                version=payload.version,
                kind=payload.kind,
                comment=payload.comment,
            )
        )
    except RecommendationError as error:
        _raise(error)
    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return RecommendationFeedbackResponse.model_validate(result)
