"""Read-only tenant member lookup endpoint."""

from typing import Annotated, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.errors import ApplicationError, ErrorResponse
from app.modules.identity.api.dependencies import ActorDependency
from app.modules.organization.application.member_service import (
    MemberForbiddenError,
    MemberPage,
    MemberService,
)
from app.modules.organization.domain.roles import MembershipRole

router = APIRouter(tags=["members"])


class MemberResponse(BaseModel):
    membership_id: UUID
    display_name: str
    role: MembershipRole
    is_active: bool


class MemberPageResponse(BaseModel):
    items: list[MemberResponse]
    page: int
    page_size: int
    total: int

    @classmethod
    def from_domain(cls, result: MemberPage) -> Self:
        return cls(
            items=[
                MemberResponse(
                    membership_id=item.membership_id,
                    display_name=item.display_name,
                    role=item.role,
                    is_active=item.is_active,
                )
                for item in result.items
            ],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        )


def get_member_service(request: Request) -> MemberService:
    return cast(MemberService, request.app.state.member_service)


MemberServiceDependency = Annotated[MemberService, Depends(get_member_service)]


@router.get(
    "/members",
    response_model=MemberPageResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def list_members(
    actor: ActorDependency,
    service: MemberServiceDependency,
    q: str | None = None,
    role: MembershipRole | None = None,
    is_active: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MemberPageResponse:
    try:
        result = await service.list_members(
            actor=actor, query=q, role=role, is_active=is_active, page=page, page_size=page_size
        )
    except MemberForbiddenError as error:
        raise ApplicationError(
            status_code=403, code="FORBIDDEN", message_key="common.error.forbidden"
        ) from error
    return MemberPageResponse.from_domain(result)
