"""Versioned People Skills endpoints."""

from __future__ import annotations

import re
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response
from fastapi import status as http_status

from app.api.errors import ApplicationError, ErrorResponse
from app.modules.identity.api.dependencies import ActorDependency
from app.modules.people_capacity.api.dependencies import (
    PeopleCapacityServiceDependency,
    PeopleMutationActorDependency,
)
from app.modules.people_capacity.api.schemas import (
    PersonSkillResponse,
    PersonSkillUpsertRequest,
    SkillCreateRequest,
    SkillResponse,
    SkillUpdateRequest,
    WorkOutcomeEvidenceCreateRequest,
    WorkOutcomeEvidenceResponse,
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

router = APIRouter(tags=["people-capacity"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
RequiredIfMatch = Annotated[str, Header(alias="If-Match")]
_ETAG = re.compile(r'^"([1-9][0-9]*)"$')
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 412, 422, 428)
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


def _raise(error: PeopleSkillError) -> NoReturn:
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
    elif isinstance(error, PeopleSkillConflictError):
        mapped = ApplicationError(
            status_code=409, code="CONFLICT", message_key="common.error.conflict"
        )
    elif isinstance(
        error,
        (
            InvalidEvidenceFieldError,
            InvalidSkillFieldError,
            InvalidSkillLevelError,
            EmptyPersonSkillPatchError,
            EmptySkillPatchError,
            PeopleSkillReferenceError,
        ),
    ):
        mapped = ApplicationError(
            status_code=422, code="VALIDATION_FAILED", message_key="common.error.validation"
        )
    else:
        raise error
    raise mapped from error


def _headers(response: Response, *, version: int, replayed: bool = False) -> None:
    response.headers["ETag"] = f'"{version}"'
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"


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
            expected_version=_required_version(if_match),
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
    try:
        result = await service.delete_skill(
            actor=actor,
            skill_id=skill_id,
            expected_version=_required_version(if_match),
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
        result = await service.set_person_skill(
            actor=actor,
            membership_id=membership_id,
            skill_id=skill_id,
            level=payload.level,
            evidence=evidence,
            expected_version=_version(if_match),
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
    try:
        result = await service.delete_person_skill(
            actor=actor,
            membership_id=membership_id,
            skill_id=skill_id,
            expected_version=_required_version(if_match),
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
