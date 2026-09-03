"""Versioned People Skills endpoints."""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from datetime import date, timedelta
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response
from fastapi import status as http_status
from fastapi.routing import APIRoute

from app.api.errors import ApplicationError, ErrorResponse, FieldError
from app.modules.identity.api.dependencies import ActorDependency
from app.modules.people_capacity.api.dependencies import (
    PeopleCapacityServiceDependency,
    PeopleMutationActorDependency,
    prepare_people_mutation,
)
from app.modules.people_capacity.api.schemas import (
    CapacityResponse,
    CapacityUpsertRequest,
    LeaveCreateRequest,
    LeaveResponse,
    LeaveUpdateRequest,
    PersonSkillResponse,
    PersonSkillUpsertRequest,
    SkillCreateRequest,
    SkillResponse,
    SkillUpdateRequest,
    WorkloadResponse,
    WorkOutcomeEvidenceCreateRequest,
    WorkOutcomeEvidenceResponse,
)
from app.modules.people_capacity.domain.availability import (
    CapacityKind,
    InvalidCapacityEntryError,
    InvalidLeaveEntryError,
    OverlappingCapacityEntriesError,
)
from app.modules.people_capacity.domain.skills import (
    EmptyPersonSkillPatchError,
    EmptySkillPatchError,
    InvalidEvidenceFieldError,
    InvalidSkillFieldError,
    InvalidSkillLevelError,
    PeopleSkillConflictError,
    PeopleSkillError,
    PeopleSkillForbiddenError,
    PeopleSkillIdempotencyKeyReusedError,
    PeopleSkillNotFoundError,
    PeopleSkillReferenceError,
    PeopleSkillVersionMismatchError,
    SkillEvidenceDraft,
    WorkOutcomeEvidenceDraft,
)


class PeopleCapacityRoute(APIRoute):
    """Run mutation authorization before FastAPI attempts request-body decoding."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        route_handler = super().get_route_handler()
        route_name = self.name

        async def preflight_handler(request: Request) -> Response:
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                await prepare_people_mutation(request, route_name=route_name)
            return await route_handler(request)

        return preflight_handler


router = APIRouter(tags=["people-capacity"], route_class=PeopleCapacityRoute)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
RequiredIfMatch = Annotated[str, Header(alias="If-Match")]
_ETAG = re.compile(r'^"([1-9][0-9]*)"$')
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 412, 422, 428, 503)
}


def _version(value: str | None) -> int | None:
    if value is None:
        return None
    match = _ETAG.fullmatch(value)
    if not match:
        raise ApplicationError(
            status_code=400, code="INVALID_REQUEST", message_key="common.error.invalidRequest"
        )
    return int(match.group(1))


def _required_version(value: str | None) -> int:
    version = _version(value)
    if version is None:
        raise ApplicationError(
            status_code=428,
            code="PRECONDITION_REQUIRED",
            message_key="common.error.preconditionRequired",
        )
    return version


def _raise(error: Exception) -> NoReturn:
    if isinstance(error, PeopleSkillForbiddenError):
        mapped = ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        )
    elif isinstance(error, PeopleSkillNotFoundError):
        mapped = ApplicationError(
            status_code=404, code="RESOURCE_NOT_FOUND", message_key="common.error.notFound"
        )
    elif isinstance(error, PeopleSkillVersionMismatchError):
        mapped = ApplicationError(
            status_code=412,
            code="RESOURCE_VERSION_MISMATCH",
            message_key="common.error.resourceVersionMismatch",
            details={"current_version": error.current_version},
        )
    elif isinstance(error, PeopleSkillIdempotencyKeyReusedError):
        mapped = ApplicationError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message_key="common.error.idempotencyKeyReused",
        )
    elif isinstance(error, (PeopleSkillConflictError, OverlappingCapacityEntriesError)):
        mapped = ApplicationError(
            status_code=409, code="CONFLICT", message_key="common.error.conflict"
        )
    elif isinstance(
        error,
        (
            InvalidEvidenceFieldError,
            InvalidSkillFieldError,
            InvalidSkillLevelError,
            InvalidCapacityEntryError,
            InvalidLeaveEntryError,
            EmptyPersonSkillPatchError,
            EmptySkillPatchError,
            PeopleSkillReferenceError,
        ),
    ):
        field = getattr(error, "field", "body")
        mapped = ApplicationError(
            status_code=422,
            code="VALIDATION_FAILED",
            message_key="common.error.validation",
            field_errors=[
                FieldError(
                    field=field,
                    code=type(error).__name__.upper(),
                    message_key="validation.invalid",
                )
            ],
        )
    else:
        raise error
    raise mapped from error


def _headers(response: Response, *, version: int, replayed: bool = False) -> None:
    response.headers["ETag"] = f'"{version}"'
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"


def _transport_validated(request: Request) -> None:
    request.state.mutation_rejection_audit = None


@router.get("/skills", response_model=list[SkillResponse], responses=_ERRORS)
async def list_skills(
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
) -> list[SkillResponse]:
    return [SkillResponse.from_domain(value) for value in await service.list_skills(actor=actor)]


@router.post(
    "/skills",
    response_model=SkillResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_skill(
    payload: SkillCreateRequest,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
) -> SkillResponse:
    _transport_validated(request)
    try:
        result = await service.create_skill(
            actor=actor,
            name=payload.name,
            description=payload.description,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return SkillResponse.from_domain(result.resource)


@router.get("/skills/{skill_id}", response_model=SkillResponse, responses=_ERRORS)
async def get_skill(
    skill_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
) -> SkillResponse:
    try:
        value = await service.get_skill(actor=actor, skill_id=skill_id)
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=value.version)
    return SkillResponse.from_domain(value)


@router.patch("/skills/{skill_id}", response_model=SkillResponse, responses=_ERRORS)
async def update_skill(
    skill_id: UUID,
    payload: SkillUpdateRequest,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: RequiredIfMatch,
) -> SkillResponse:
    supplied = payload.model_fields_set
    expected_version = _required_version(if_match)
    _transport_validated(request)
    try:
        result = await service.update_skill(
            actor=actor,
            skill_id=skill_id,
            name=payload.name,
            name_supplied="name" in supplied,
            description=payload.description,
            description_supplied="description" in supplied,
            active=payload.active,
            active_supplied="active" in supplied,
            expected_version=expected_version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return SkillResponse.from_domain(result.resource)


@router.delete("/skills/{skill_id}", response_model=SkillResponse, responses=_ERRORS)
async def delete_skill(
    skill_id: UUID,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: RequiredIfMatch,
) -> SkillResponse:
    expected_version = _required_version(if_match)
    _transport_validated(request)
    try:
        result = await service.delete_skill(
            actor=actor,
            skill_id=skill_id,
            expected_version=expected_version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return SkillResponse.from_domain(result.resource)


@router.get(
    "/members/{membership_id}/skills",
    response_model=list[PersonSkillResponse],
    responses=_ERRORS,
)
async def list_person_skills(
    membership_id: UUID,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
) -> list[PersonSkillResponse]:
    try:
        values = await service.list_person_skills(actor=actor, membership_id=membership_id)
    except PeopleSkillError as error:
        _raise(error)
    return [
        PersonSkillResponse.from_domain(
            value,
            await service.list_skill_evidence(actor=actor, person_skill_id=value.id),
        )
        for value in values
    ]


@router.get(
    "/members/{membership_id}/skills/{skill_id}",
    response_model=PersonSkillResponse,
    responses=_ERRORS,
)
async def get_person_skill(
    membership_id: UUID,
    skill_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
) -> PersonSkillResponse:
    try:
        value = await service.get_person_skill(
            actor=actor, membership_id=membership_id, skill_id=skill_id
        )
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=value.version)
    return PersonSkillResponse.from_domain(
        value,
        await service.list_skill_evidence(actor=actor, person_skill_id=value.id),
    )


@router.put(
    "/members/{membership_id}/skills/{skill_id}",
    response_model=PersonSkillResponse,
    responses=_ERRORS,
)
async def set_person_skill(
    membership_id: UUID,
    skill_id: UUID,
    payload: PersonSkillUpsertRequest,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> PersonSkillResponse:
    if payload.skill_id != skill_id:
        raise ApplicationError(
            status_code=422, code="VALIDATION_FAILED", message_key="common.error.validation"
        )
    try:
        evidence = tuple(
            SkillEvidenceDraft.create(**item.model_dump()) for item in payload.evidence
        )
        expected_version = _version(if_match)
        _transport_validated(request)
        result = await service.set_person_skill(
            actor=actor,
            membership_id=membership_id,
            skill_id=skill_id,
            level=payload.level,
            evidence=evidence,
            expected_version=expected_version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return PersonSkillResponse.from_domain(
        result.resource,
        result.evidence,
    )


@router.delete(
    "/members/{membership_id}/skills/{skill_id}",
    response_model=PersonSkillResponse,
    responses=_ERRORS,
)
async def delete_person_skill(
    membership_id: UUID,
    skill_id: UUID,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: RequiredIfMatch,
) -> PersonSkillResponse:
    expected_version = _required_version(if_match)
    _transport_validated(request)
    try:
        result = await service.delete_person_skill(
            actor=actor,
            membership_id=membership_id,
            skill_id=skill_id,
            expected_version=expected_version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return PersonSkillResponse.from_domain(
        result.resource,
        result.evidence,
    )


@router.get(
    "/members/{membership_id}/work-evidence",
    response_model=list[WorkOutcomeEvidenceResponse],
    responses=_ERRORS,
)
async def list_work_outcome_evidence(
    membership_id: UUID,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
) -> list[WorkOutcomeEvidenceResponse]:
    try:
        values = await service.list_work_outcome_evidence(actor=actor, membership_id=membership_id)
    except PeopleSkillError as error:
        _raise(error)
    return [WorkOutcomeEvidenceResponse.from_domain(value) for value in values]


@router.post(
    "/members/{membership_id}/work-evidence",
    response_model=WorkOutcomeEvidenceResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def record_work_outcome_evidence(
    membership_id: UUID,
    payload: WorkOutcomeEvidenceCreateRequest,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
) -> WorkOutcomeEvidenceResponse:
    try:
        evidence = WorkOutcomeEvidenceDraft.create(
            evidence_type=payload.evidence_type,
            summary=payload.summary,
            source_resource_type=payload.source_resource_type,
            source_resource_id=payload.source_resource_id,
            source_resource_version=payload.source_resource_version,
            observed_at=payload.observed_at,
        )
        _transport_validated(request)
        result = await service.record_work_outcome_evidence(
            actor=actor,
            membership_id=membership_id,
            evidence=evidence,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except PeopleSkillError as error:
        _raise(error)
    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return WorkOutcomeEvidenceResponse.from_domain(result.resource)


@router.get(
    "/capacity",
    response_model=list[CapacityResponse],
    responses=_ERRORS,
)
async def list_capacity(
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
    membership_id: UUID | None = None,
    kind: CapacityKind | None = None,
) -> list[CapacityResponse]:
    try:
        entries = await service.list_capacity(actor=actor, membership_id=membership_id, kind=kind)
    except PeopleSkillError as error:
        _raise(error)
    return [CapacityResponse.from_domain(entry) for entry in entries]


@router.post(
    "/capacity",
    response_model=CapacityResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def upsert_capacity(
    payload: CapacityUpsertRequest,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch = None,
) -> CapacityResponse:
    if payload.kind == "DEFAULT":
        if payload.week_start is not None:
            raise ApplicationError(
                status_code=422,
                code="VALIDATION_FAILED",
                message_key="common.error.validation",
                field_errors=[
                    FieldError(
                        field="week_start",
                        code="WEEK_START_NOT_ALLOWED",
                        message_key="validation.invalid",
                    )
                ],
            )
        eff_from = payload.effective_from or date(2000, 1, 1)
        eff_to = payload.effective_to or date(2099, 12, 31)
    else:
        if payload.week_start is None:
            raise ApplicationError(
                status_code=422,
                code="VALIDATION_FAILED",
                message_key="common.error.validation",
                field_errors=[
                    FieldError(
                        field="week_start",
                        code="WEEK_START_REQUIRED",
                        message_key="validation.invalid",
                    )
                ],
            )
        eff_from = payload.effective_from or payload.week_start
        eff_to = payload.effective_to or (payload.week_start + timedelta(days=6))

    _transport_validated(request)
    try:
        expected_version = _version(if_match)
        result = await service.upsert_capacity(
            actor=actor,
            membership_id=payload.membership_id,
            kind=CapacityKind(payload.kind),
            hours=payload.hours,
            effective_from=eff_from,
            effective_to=eff_to,
            week_start=payload.week_start,
            expected_version=expected_version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    if expected_version is not None:
        response.status_code = http_status.HTTP_200_OK
    return CapacityResponse.from_domain(result.resource)


@router.get(
    "/capacity/{capacity_id}",
    response_model=CapacityResponse,
    responses=_ERRORS,
)
async def get_capacity(
    capacity_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
) -> CapacityResponse:
    try:
        entry = await service.get_capacity(actor=actor, capacity_id=capacity_id)
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=entry.version)
    return CapacityResponse.from_domain(entry)


@router.delete(
    "/capacity/{capacity_id}",
    response_model=CapacityResponse,
    responses=_ERRORS,
)
async def delete_capacity(
    capacity_id: UUID,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: RequiredIfMatch,
) -> CapacityResponse:
    _transport_validated(request)
    try:
        expected_version = _required_version(if_match)
        result = await service.delete_capacity(
            actor=actor,
            capacity_id=capacity_id,
            expected_version=expected_version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return CapacityResponse.from_domain(result.resource)


@router.get(
    "/leave",
    response_model=list[LeaveResponse],
    responses=_ERRORS,
)
async def list_leave(
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
    membership_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[LeaveResponse]:
    try:
        entries = await service.list_leave(
            actor=actor,
            membership_id=membership_id,
            start_date=start_date,
            end_date=end_date,
        )
    except PeopleSkillError as error:
        _raise(error)
    return [LeaveResponse.from_domain(entry) for entry in entries]


@router.post(
    "/leave",
    response_model=LeaveResponse,
    status_code=http_status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_leave(
    payload: LeaveCreateRequest,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
) -> LeaveResponse:
    _transport_validated(request)
    try:
        result = await service.create_leave(
            actor=actor,
            membership_id=payload.membership_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            unavailable_hours=payload.unavailable_hours,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    if result.replayed:
        response.status_code = http_status.HTTP_200_OK
    return LeaveResponse.from_domain(result.resource)


@router.get(
    "/leave/{leave_id}",
    response_model=LeaveResponse,
    responses=_ERRORS,
)
async def get_leave(
    leave_id: UUID,
    response: Response,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
) -> LeaveResponse:
    try:
        entry = await service.get_leave(actor=actor, leave_id=leave_id)
    except PeopleSkillError as error:
        _raise(error)
    _headers(response, version=entry.version)
    return LeaveResponse.from_domain(entry)


@router.patch(
    "/leave/{leave_id}",
    response_model=LeaveResponse,
    responses=_ERRORS,
)
async def update_leave(
    leave_id: UUID,
    payload: LeaveUpdateRequest,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: RequiredIfMatch,
) -> LeaveResponse:
    _transport_validated(request)
    supplied = payload.model_fields_set
    try:
        result = await service.update_leave(
            actor=actor,
            leave_id=leave_id,
            start_date=payload.start_date,
            start_date_supplied="start_date" in supplied,
            end_date=payload.end_date,
            end_date_supplied="end_date" in supplied,
            unavailable_hours=payload.unavailable_hours,
            unavailable_hours_supplied="unavailable_hours" in supplied,
            expected_version=_required_version(if_match),
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return LeaveResponse.from_domain(result.resource)


@router.delete(
    "/leave/{leave_id}",
    response_model=LeaveResponse,
    responses=_ERRORS,
)
async def delete_leave(
    leave_id: UUID,
    request: Request,
    response: Response,
    actor: PeopleMutationActorDependency,
    service: PeopleCapacityServiceDependency,
    idempotency_key: IdempotencyKey,
    if_match: RequiredIfMatch,
) -> LeaveResponse:
    _transport_validated(request)
    try:
        expected_version = _required_version(if_match)
        result = await service.delete_leave(
            actor=actor,
            leave_id=leave_id,
            expected_version=expected_version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise(error)
    _headers(response, version=result.resource.version, replayed=result.replayed)
    return LeaveResponse.from_domain(result.resource)


@router.get(
    "/workload",
    response_model=list[WorkloadResponse],
    responses=_ERRORS,
)
async def list_weekly_workload(
    week_start: date,
    actor: ActorDependency,
    service: PeopleCapacityServiceDependency,
    membership_id: UUID | None = None,
) -> list[WorkloadResponse]:
    try:
        workloads = await service.list_weekly_workload(
            actor=actor,
            week_start=week_start,
            membership_id=membership_id,
        )
    except PeopleSkillError as error:
        _raise(error)
    return [WorkloadResponse.from_domain(item) for item in workloads]
