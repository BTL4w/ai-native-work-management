"""Authenticated actor and local-auth domain values."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.organization.domain.roles import MembershipRole


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """Trusted identity and tenant membership resolved from a valid session."""

    user_id: UUID
    email: str
    display_name: str
    membership_id: UUID
    organization_id: UUID
    organization_name: str
    role: MembershipRole


@dataclass(frozen=True, slots=True)
class LoginIdentity:
    """Global identity fields used only inside the authentication boundary."""

    user_id: UUID
    email: str
    display_name: str
    password_hash: str
    is_active: bool


class InvalidCredentialsError(Exception):
    """Credentials do not resolve to an active local membership."""


class AuthenticationRequiredError(Exception):
    """No usable session credential was supplied."""


class SessionExpiredError(Exception):
    """A supplied session credential is invalid, revoked, or expired."""
