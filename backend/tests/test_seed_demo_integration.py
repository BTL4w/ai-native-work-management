"""PostgreSQL integration test for idempotent demo seed behavior."""

from __future__ import annotations

import os
from uuid import uuid4

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
from app.modules.people_capacity.adapters.database_models import (
    CapacityEntryModel,
    LeaveEntryModel,
    PersonSkillModel,
    SkillEvidenceModel,
    SkillModel,
    SkillVersionModel,
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
                staff_emails = (
                    "an.nguyen@example.test",
                    "binh.tran@example.test",
                    "canh.le@example.test",
                    "dung.pham@example.test",
                    "ha.vo@example.test",
                    "huy.nguyen@example.test",
                    "linh.tran@example.test",
                    "minh.phan@example.test",
                    "nam.do@example.test",
                    "nguyen.bui@example.test",
                    "phuc.ho@example.test",
                    "quan.vu@example.test",
                    "trang.dang@example.test",
                    "tu.ly@example.test",
                    "van.mai@example.test",
                )
                demo_emails = (*tuple(account.email for account in DEMO_ACCOUNTS), *staff_emails)
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
                skill_count = await _organization_count(session, SkillModel, first.organization_id)
                skill_version_count = await _organization_count(
                    session, SkillVersionModel, first.organization_id
                )
                person_skill_count = await _organization_count(
                    session, PersonSkillModel, first.organization_id
                )
                evidence_count = await _organization_count(
                    session, SkillEvidenceModel, first.organization_id
                )
                capacity_count = await _organization_count(
                    session, CapacityEntryModel, first.organization_id
                )
                leave_count = await _organization_count(
                    session, LeaveEntryModel, first.organization_id
                )
                staff_names = set(
                    (
                        await session.scalars(
                            select(UserModel.display_name)
                            .join(MembershipModel, MembershipModel.user_id == UserModel.id)
                            .where(
                                MembershipModel.organization_id == first.organization_id,
                                UserModel.email_normalized.in_(staff_emails),
                            )
                        )
                    ).all()
                )

                assert first.organization_created is True
                assert first.users_created == len(demo_emails) - existing_user_count
                assert first.memberships_created == 18
                assert second.organization_created is False
                assert second.users_created == 0
                assert second.memberships_created == 0
                assert organization_count == 1
                assert membership_count == 18
                assert skill_count == 28
                assert skill_version_count == 28
                assert person_skill_count == 60
                assert evidence_count == 60
                assert capacity_count == 15
                assert leave_count == 2
                assert staff_names == {
                    "Nguyễn Hoàng An",
                    "Trần Gia Bình",
                    "Lê Minh Cảnh",
                    "Phạm Quốc Dũng",
                    "Võ Thu Hà",
                    "Nguyễn Đức Huy",
                    "Trần Khánh Linh",
                    "Phan Tuấn Minh",
                    "Đỗ Ngọc Nam",
                    "Bùi Thảo Nguyên",
                    "Hồ Quang Phúc",
                    "Vũ Bảo Quân",
                    "Đặng Mai Trang",
                    "Lý Anh Tú",
                    "Mai Thanh Vân",
                }

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


@pytest.mark.asyncio
async def test_seed_orders_workforce_dependencies_for_an_existing_organization() -> None:
    slug = f"seed-existing-{uuid4().hex}"
    settings = Settings(
        environment="test",
        local_auth_organization_slug=slug,
        local_auth_organization_name="Existing Seed Test",
        demo_seed_password=SecretStr("IntegrationSeed123!"),
    )
    engine = create_database_engine(settings)

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                organization = OrganizationModel(id=uuid4(), slug=slug, name="Existing Seed Test")
                session.add(organization)
                await session.flush()
                for account in DEMO_ACCOUNTS:
                    user = await session.scalar(
                        select(UserModel).where(UserModel.email_normalized == account.email)
                    )
                    if user is None:
                        user = UserModel(
                            id=uuid4(),
                            email_normalized=account.email,
                            email_display=account.email,
                            display_name=account.display_name,
                            password_hash=PasswordHash.recommended().hash("IntegrationSeed123!"),
                            is_active=True,
                        )
                        session.add(user)
                    session.add(
                        MembershipModel(
                            id=uuid4(),
                            organization_id=organization.id,
                            user_id=user.id,
                            role=account.role,
                            is_active=True,
                        )
                    )
                await session.flush()

                result = await seed_demo_data(session, settings)

                assert result.organization_created is False
                assert await _organization_count(session, SkillModel, result.organization_id) == 28
                assert (
                    await _organization_count(session, PersonSkillModel, result.organization_id)
                    == 60
                )
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


async def _organization_count(
    session: AsyncSession, model: type[object], organization_id: object
) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.organization_id == organization_id)  # type: ignore[attr-defined]
        )
        or 0
    )
