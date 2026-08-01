"""Transactional local authentication use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.modules.identity.application.ports import (
    AuthTransactionFactory,
    PasswordVerifier,
    SessionTokenCodec,
)
from app.modules.identity.domain.auth import (
    AuthenticatedActor,
    AuthenticationRequiredError,
    InvalidCredentialsError,
    SessionExpiredError,
)


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Authenticated actor plus the one-time raw cookie credential."""

    actor: AuthenticatedActor
    cookie_value: str


class AuthService:
    """Own login/session transaction boundaries and deterministic decisions."""

    def __init__(
        self,
        *,
        transaction_factory: AuthTransactionFactory,
        password_verifier: PasswordVerifier,
        token_codec: SessionTokenCodec,
        organization_slug: str,
        session_ttl_seconds: int,
    ) -> None:
        self._transaction_factory = transaction_factory
        self._password_verifier = password_verifier
        self._token_codec = token_codec
        self._organization_slug = organization_slug
        self._session_ttl = timedelta(seconds=session_ttl_seconds)

    async def login(self, *, email: str, password: str, request_id: str) -> LoginResult:
        """Verify local credentials and create a tenant-scoped opaque session."""

        normalized_email = email.strip().casefold()
        now = datetime.now(UTC)
        result: LoginResult | None = None
        credentials_rejected = False
        async with self._transaction_factory() as repository:
            organization = await repository.find_organization(self._organization_slug)
            identity = await repository.find_user(normalized_email)
            password_valid = self._password_verifier.verify(
                password, identity.password_hash if identity is not None else None
            )
            if organization is None or identity is None:
                raise InvalidCredentialsError

            organization_id, _ = organization
            await repository.activate_tenant(organization_id)
            actor = await repository.find_membership_actor(organization_id, identity)
            if not password_valid or not identity.is_active or actor is None:
                await repository.add_audit_event(
                    organization_id=organization_id,
                    actor_membership_id=actor.membership_id if actor is not None else None,
                    action="auth.login.rejected",
                    outcome="REJECTED",
                    request_id=request_id,
                    reason_data={"code": "INVALID_CREDENTIALS"},
                )
                credentials_rejected = True
            else:
                cookie_value, token_hash = self._token_codec.issue(organization_id)
                await repository.create_session(
                    organization_id=organization_id,
                    membership_id=actor.membership_id,
                    token_hash=token_hash,
                    expires_at=now + self._session_ttl,
                )
                await repository.add_audit_event(
                    organization_id=organization_id,
                    actor_membership_id=actor.membership_id,
                    action="auth.login.succeeded",
                    outcome="SUCCEEDED",
                    request_id=request_id,
                )
                result = LoginResult(actor=actor, cookie_value=cookie_value)

        if credentials_rejected or result is None:
            raise InvalidCredentialsError
        return result

    async def authenticate(self, cookie_value: str | None) -> AuthenticatedActor:
        """Resolve a valid session while treating its organization id only as a locator."""

        if cookie_value is None:
            raise AuthenticationRequiredError
        parsed = self._token_codec.parse_and_hash(cookie_value)
        if parsed is None:
            raise SessionExpiredError

        organization_id, token_hash = parsed
        now = datetime.now(UTC)
        async with self._transaction_factory() as repository:
            await repository.activate_tenant(organization_id)
            actor = await repository.find_active_session_actor(
                organization_id=organization_id,
                token_hash=token_hash,
                now=now,
            )
            if actor is None:
                raise SessionExpiredError
            return actor

    async def logout(self, *, cookie_value: str | None, request_id: str) -> None:
        """Revoke a valid session; missing, malformed, and repeated calls remain safe."""

        if cookie_value is None:
            return
        parsed = self._token_codec.parse_and_hash(cookie_value)
        if parsed is None:
            return

        organization_id, token_hash = parsed
        now = datetime.now(UTC)
        async with self._transaction_factory() as repository:
            await repository.activate_tenant(organization_id)
            actor = await repository.revoke_session(
                organization_id=organization_id,
                token_hash=token_hash,
                now=now,
            )
            if actor is not None:
                await repository.add_audit_event(
                    organization_id=organization_id,
                    actor_membership_id=actor.membership_id,
                    action="auth.logout.succeeded",
                    outcome="SUCCEEDED",
                    request_id=request_id,
                )
