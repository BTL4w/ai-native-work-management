"""Idempotently seed the local organization and three Phase 1 personas."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import create_database_engine, create_session_factory
from app.modules.identity.adapters.database_models import UserModel
from app.modules.organization.adapters.database_models import (
    MembershipModel,
    OrganizationModel,
)
from app.modules.organization.domain.roles import MembershipRole

_PASSWORD_HASH = PasswordHash.recommended()


@dataclass(frozen=True, slots=True)
class DemoAccount:
    """Non-secret identity fields for one local demo persona."""

    email: str
    display_name: str
    role: MembershipRole


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Summary safe to print without exposing credentials or hashes."""

    organization_id: UUID
    organization_created: bool
    users_created: int
    memberships_created: int


DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    DemoAccount("admin@example.test", "Demo Admin", MembershipRole.ADMIN),
    DemoAccount("manager@example.test", "Demo Manager", MembershipRole.MANAGER),
    DemoAccount("employee@example.test", "Demo Employee", MembershipRole.EMPLOYEE),
)


def ensure_demo_seed_allowed(settings: Settings) -> None:
    """Fail closed unless the command is explicitly enabled in local mode."""

    if settings.environment != "local" or not settings.demo_seed_enabled:
        msg = "demo seed requires APP_ENVIRONMENT=local and APP_DEMO_SEED_ENABLED=true"
        raise RuntimeError(msg)


async def _get_or_create_organization(
    session: AsyncSession, settings: Settings
) -> tuple[OrganizationModel, bool]:
    organization = await session.scalar(
        select(OrganizationModel).where(
            OrganizationModel.slug == settings.local_auth_organization_slug
        )
    )
    if organization is not None:
        organization.name = settings.local_auth_organization_name
        return organization, False

    organization = OrganizationModel(
        id=uuid4(),
        slug=settings.local_auth_organization_slug,
        name=settings.local_auth_organization_name,
    )
    session.add(organization)
    await session.flush()
    return organization, True


async def _get_or_create_user(
    session: AsyncSession,
    account: DemoAccount,
    password: str,
) -> tuple[UserModel, bool]:
    user = await session.scalar(
        select(UserModel).where(UserModel.email_normalized == account.email)
    )
    if user is not None:
        user.email_display = account.email
        user.display_name = account.display_name
        user.is_active = True
        if not _PASSWORD_HASH.verify(password, user.password_hash):
            user.password_hash = _PASSWORD_HASH.hash(password)
        return user, False

    user = UserModel(
        id=uuid4(),
        email_normalized=account.email,
        email_display=account.email,
        display_name=account.display_name,
        password_hash=_PASSWORD_HASH.hash(password),
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user, True


async def _get_or_create_membership(
    session: AsyncSession,
    organization: OrganizationModel,
    user: UserModel,
    role: MembershipRole,
) -> bool:
    membership = await session.scalar(
        select(MembershipModel).where(
            MembershipModel.organization_id == organization.id,
            MembershipModel.user_id == user.id,
        )
    )
    if membership is not None:
        membership.role = role
        membership.is_active = True
        return False

    session.add(
        MembershipModel(
            id=uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            is_active=True,
        )
    )
    return True


async def seed_demo_data(session: AsyncSession, settings: Settings) -> SeedResult:
    """Create or reconcile the fixed local demo records in one transaction."""

    password = settings.demo_seed_password.get_secret_value()
    organization, organization_created = await _get_or_create_organization(session, settings)
    users_created = 0
    memberships_created = 0
    demo_user_ids: list[UUID] = []

    for account in DEMO_ACCOUNTS:
        user, was_created = await _get_or_create_user(session, account, password)
        demo_user_ids.append(user.id)
        users_created += int(was_created)
        memberships_created += int(
            await _get_or_create_membership(session, organization, user, account.role)
        )

    await session.flush()
    membership_count = await session.scalar(
        select(func.count())
        .select_from(MembershipModel)
        .where(
            MembershipModel.organization_id == organization.id,
            MembershipModel.user_id.in_(demo_user_ids),
        )
    )
    if membership_count != len(DEMO_ACCOUNTS):
        msg = "demo seed post-condition failed: unexpected membership count"
        raise RuntimeError(msg)

    return SeedResult(
        organization_id=organization.id,
        organization_created=organization_created,
        users_created=users_created,
        memberships_created=memberships_created,
    )


async def run_seed(settings: Settings) -> SeedResult:
    """Validate local policy, execute one transaction and release the pool."""

    ensure_demo_seed_allowed(settings)
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as session:
            return await seed_demo_data(session, settings)
    finally:
        await engine.dispose()


def main() -> None:
    """CLI entrypoint for `python -m app.scripts.seed_demo`."""

    result = asyncio.run(run_seed(get_settings()))
    print(
        "Demo seed complete: "
        f"organization={result.organization_id}, "
        f"new_users={result.users_created}, "
        f"new_memberships={result.memberships_created}"
    )


if __name__ == "__main__":
    main()
