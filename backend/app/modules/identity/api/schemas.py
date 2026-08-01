"""Typed public authentication request and response schemas."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole


class LoginRequest(BaseModel):
    """Local credential input; password representation is redacted by Pydantic."""

    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)


class MeUserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str


class MeMembershipResponse(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    role: MembershipRole


class MeResponse(BaseModel):
    user: MeUserResponse
    membership: MeMembershipResponse

    @classmethod
    def from_actor(cls, actor: AuthenticatedActor) -> Self:
        return cls(
            user=MeUserResponse(
                id=actor.user_id,
                email=actor.email,
                display_name=actor.display_name,
            ),
            membership=MeMembershipResponse(
                id=actor.membership_id,
                organization_id=actor.organization_id,
                organization_name=actor.organization_name,
                role=actor.role,
            ),
        )
