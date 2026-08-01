"""SQLAlchemy implementation of the authentication persistence port."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.adapters.database_models import AuditEventModel
from app.modules.audit.domain.events import AuditOutcome
from app.modules.identity.adapters.database_models import AuthSessionModel, UserModel
from app.modules.identity.application.ports import AuthRepository
from app.modules.identity.domain.auth import AuthenticatedActor, LoginIdentity
from app.modules.organization.adapters.database_models import (
    MembershipModel,
    OrganizationModel,
)


class SqlAlchemyAuthRepository:
    """Run auth persistence operations on one caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_organization(self, slug: str) -> tuple[UUID, str] | None:
        row = (
            await self._session.execute(
                select(OrganizationModel.id, OrganizationModel.name).where(
                    OrganizationModel.slug == slug
                )
            )
        ).one_or_none()
        return (row.id, row.name) if row is not None else None

    async def find_user(self, normalized_email: str) -> LoginIdentity | None:
        user = await self._session.scalar(
            select(UserModel).where(UserModel.email_normalized == normalized_email)
        )
        if user is None:
            return None
        return LoginIdentity(
            user_id=user.id,
            email=user.email_display,
            display_name=user.display_name,
            password_hash=user.password_hash,
            is_active=user.is_active,
        )

    async def activate_tenant(self, organization_id: UUID) -> None:
        await self._session.execute(text("SET LOCAL ROLE app_runtime"))
        await self._session.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )

    async def find_membership_actor(
        self, organization_id: UUID, identity: LoginIdentity
    ) -> AuthenticatedActor | None:
        row = (
            await self._session.execute(
                select(MembershipModel, OrganizationModel.name)
                .join(
                    OrganizationModel,
                    OrganizationModel.id == MembershipModel.organization_id,
                )
                .where(
                    MembershipModel.organization_id == organization_id,
                    MembershipModel.user_id == identity.user_id,
                    MembershipModel.is_active.is_(True),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        membership, organization_name = row
        return AuthenticatedActor(
            user_id=identity.user_id,
            email=identity.email,
            display_name=identity.display_name,
            membership_id=membership.id,
            organization_id=membership.organization_id,
            organization_name=organization_name,
            role=membership.role,
        )

    async def create_session(
        self,
        *,
        organization_id: UUID,
        membership_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            AuthSessionModel(
                id=uuid4(),
                organization_id=organization_id,
                membership_id=membership_id,
                token_hash=token_hash,
                expires_at=expires_at,
                revoked_at=None,
                last_seen_at=None,
            )
        )

    async def find_active_session_actor(
        self, *, organization_id: UUID, token_hash: str, now: datetime
    ) -> AuthenticatedActor | None:
        row = (
            await self._session.execute(
                select(AuthSessionModel, MembershipModel, UserModel, OrganizationModel.name)
                .join(
                    MembershipModel,
                    (MembershipModel.organization_id == AuthSessionModel.organization_id)
                    & (MembershipModel.id == AuthSessionModel.membership_id),
                )
                .join(UserModel, UserModel.id == MembershipModel.user_id)
                .join(OrganizationModel, OrganizationModel.id == AuthSessionModel.organization_id)
                .where(
                    AuthSessionModel.organization_id == organization_id,
                    AuthSessionModel.token_hash == token_hash,
                    AuthSessionModel.revoked_at.is_(None),
                    AuthSessionModel.expires_at > now,
                    MembershipModel.is_active.is_(True),
                    UserModel.is_active.is_(True),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        session, membership, user, organization_name = row
        session.last_seen_at = now
        return AuthenticatedActor(
            user_id=user.id,
            email=user.email_display,
            display_name=user.display_name,
            membership_id=membership.id,
            organization_id=membership.organization_id,
            organization_name=organization_name,
            role=membership.role,
        )

    async def revoke_session(
        self, *, organization_id: UUID, token_hash: str, now: datetime
    ) -> AuthenticatedActor | None:
        actor = await self.find_active_session_actor(
            organization_id=organization_id, token_hash=token_hash, now=now
        )
        if actor is None:
            return None
        auth_session = await self._session.scalar(
            select(AuthSessionModel).where(
                AuthSessionModel.organization_id == organization_id,
                AuthSessionModel.token_hash == token_hash,
            )
        )
        if auth_session is None:
            return None
        auth_session.revoked_at = now
        return actor

    async def add_audit_event(
        self,
        *,
        organization_id: UUID,
        actor_membership_id: UUID | None,
        action: str,
        outcome: str,
        request_id: str,
        reason_data: dict[str, object] | None = None,
    ) -> None:
        self._session.add(
            AuditEventModel(
                id=uuid4(),
                organization_id=organization_id,
                actor_membership_id=actor_membership_id,
                action=action,
                outcome=AuditOutcome(outcome),
                resource_type=None,
                resource_id=None,
                request_id=request_id,
                idempotency_key=None,
                before_data={},
                after_data={},
                reason_data=reason_data or {},
            )
        )


class SqlAlchemyAuthTransactionFactory:
    """Create one committed-or-rolled-back session per authentication use case."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AuthRepository]:
        async with self._session_factory.begin() as session:
            yield SqlAlchemyAuthRepository(session)
