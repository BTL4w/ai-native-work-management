"""PostgreSQL integration test for idempotent demo seed behavior."""

from __future__ import annotations

import os

import pytest
from pwdlib import PasswordHash
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import create_database_engine
from app.modules.identity.adapters.database_models import UserModel
from app.modules.organization.adapters.database_models import (
    MembershipModel,
    OrganizationModel,
)
from app.scripts.seed_demo import DEMO_ACCOUNTS, seed_demo_data

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 with local PostgreSQL running",
    ),
]


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_stores_argon2_hashes() -> None:
    settings = Settings(
        environment="test",
        local_auth_organization_slug="seed-test",
        local_auth_organization_name="Seed Test",
        demo_seed_password=SecretStr("IntegrationSeed123!"),
    )
    engine = create_database_engine(settings)

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                demo_emails = tuple(account.email for account in DEMO_ACCOUNTS)
                existing_user_count = (
                    await session.scalar(
                        select(func.count())
                        .select_from(UserModel)
                        .where(UserModel.email_normalized.in_(demo_emails))
                    )
                    or 0
                )
                first = await seed_demo_data(session, settings)
                first_hashes = {
                    user.email_normalized: user.password_hash
                    for user in (
                        await session.scalars(
                            select(UserModel).where(UserModel.email_normalized.in_(demo_emails))
                        )
                    ).all()
                }
                second = await seed_demo_data(session, settings)

                organization_count = await session.scalar(
                    select(func.count())
                    .select_from(OrganizationModel)
                    .where(OrganizationModel.slug == settings.local_auth_organization_slug)
                )
                membership_count = await session.scalar(
                    select(func.count())
                    .select_from(MembershipModel)
                    .where(MembershipModel.organization_id == first.organization_id)
                )

                assert first.organization_created is True
                assert first.users_created == len(DEMO_ACCOUNTS) - existing_user_count
                assert first.memberships_created == 3
                assert second.organization_created is False
                assert second.users_created == 0
                assert second.memberships_created == 0
                assert organization_count == 1
                assert membership_count == 3

                password_hash = PasswordHash.recommended()
                for encoded_hash in first_hashes.values():
                    assert encoded_hash.startswith("$argon2")
                    assert password_hash.verify(
                        settings.demo_seed_password.get_secret_value(), encoded_hash
                    )
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()
