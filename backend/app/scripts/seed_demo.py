"""Idempotently seed local demo personas and a realistic IT workforce."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4, uuid5

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
from app.modules.people_capacity.adapters.database_models import (
    CapacityEntryModel,
    LeaveEntryModel,
    PersonSkillModel,
    SkillEvidenceModel,
    SkillModel,
    SkillVersionModel,
)
from app.modules.people_capacity.domain.availability import CapacityKind
from app.modules.people_capacity.domain.skills import SkillEvidenceType

_PASSWORD_HASH = PasswordHash.recommended()
_DEMO_NAMESPACE = UUID("4ac5ef6a-9a66-4f1e-92d5-e5221e50a7c8")
_VERIFIED_AT = datetime(2026, 9, 1, 9, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DemoAccount:
    """Non-secret identity fields for one local demo persona."""

    email: str
    display_name: str
    role: MembershipRole


@dataclass(frozen=True, slots=True)
class DemoSkill:
    """One organization Skill managed by the local demo seed."""

    name: str
    description: str


@dataclass(frozen=True, slots=True)
class DemoStaff:
    """One realistic IT Employee profile and its verified capabilities."""

    email: str
    display_name: str
    capacity_hours: int
    skills: tuple[tuple[str, int], ...]
    leave_hours: int = 0


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

DEMO_SKILLS: tuple[DemoSkill, ...] = (
    DemoSkill("Project Management", "Planning, delivery coordination, scope and risk management."),
    DemoSkill("Product Management", "Product discovery, prioritization and outcome ownership."),
    DemoSkill("Business Analysis", "Requirements discovery, process analysis and specification."),
    DemoSkill("Agile/Scrum", "Iterative delivery, facilitation and continuous improvement."),
    DemoSkill("UX Research", "User research, journey mapping and usability evaluation."),
    DemoSkill("UI Design", "Accessible interface and interaction design."),
    DemoSkill("Figma", "Collaborative interface design and prototyping."),
    DemoSkill("HTML/CSS", "Semantic, responsive and accessible web presentation."),
    DemoSkill("TypeScript", "Type-safe application development with TypeScript."),
    DemoSkill("React", "Component-driven web application development with React."),
    DemoSkill("Python", "Production Python application and automation development."),
    DemoSkill("FastAPI", "Typed asynchronous API development with FastAPI."),
    DemoSkill("Java", "Production backend development with Java."),
    DemoSkill("Spring Boot", "Service and API development with Spring Boot."),
    DemoSkill("Flutter", "Cross-platform mobile application development."),
    DemoSkill("Manual Testing", "Exploratory, functional and acceptance testing."),
    DemoSkill("Test Automation", "Reliable automated test design and maintenance."),
    DemoSkill("Playwright", "Browser-based end-to-end test automation."),
    DemoSkill("DevOps", "Delivery automation, observability and operational practices."),
    DemoSkill("Docker", "Container image design and local container orchestration."),
    DemoSkill("Kubernetes", "Container workload orchestration and operations."),
    DemoSkill("Cloud Infrastructure", "Secure and resilient cloud infrastructure engineering."),
    DemoSkill("PostgreSQL", "Relational data modeling, querying and operations."),
    DemoSkill("Data Engineering", "Reliable data ingestion, transformation and serving."),
    DemoSkill("Machine Learning", "Applied machine-learning development and evaluation."),
    DemoSkill("Cybersecurity", "Application, infrastructure and operational security."),
    DemoSkill("Networking", "Enterprise network design, diagnosis and operations."),
    DemoSkill("IT Support", "End-user systems support and incident resolution."),
)

IT_STAFF: tuple[DemoStaff, ...] = (
    DemoStaff(
        "an.nguyen@example.test",
        "Nguyễn Hoàng An",
        36,
        (
            ("Project Management", 5),
            ("Product Management", 4),
            ("Agile/Scrum", 4),
            ("Business Analysis", 3),
        ),
    ),
    DemoStaff(
        "binh.tran@example.test",
        "Trần Gia Bình",
        40,
        (
            ("Business Analysis", 5),
            ("Product Management", 4),
            ("Agile/Scrum", 4),
            ("PostgreSQL", 3),
        ),
    ),
    DemoStaff(
        "canh.le@example.test",
        "Lê Minh Cảnh",
        32,
        (("UX Research", 5), ("UI Design", 5), ("Figma", 5), ("HTML/CSS", 3)),
        leave_hours=8,
    ),
    DemoStaff(
        "dung.pham@example.test",
        "Phạm Quốc Dũng",
        40,
        (("TypeScript", 5), ("React", 5), ("HTML/CSS", 5), ("Playwright", 3)),
    ),
    DemoStaff(
        "ha.vo@example.test",
        "Võ Thu Hà",
        36,
        (("React", 4), ("TypeScript", 4), ("UI Design", 3), ("Test Automation", 3)),
    ),
    DemoStaff(
        "huy.nguyen@example.test",
        "Nguyễn Đức Huy",
        40,
        (("Python", 5), ("FastAPI", 5), ("PostgreSQL", 4), ("Docker", 3)),
    ),
    DemoStaff(
        "linh.tran@example.test",
        "Trần Khánh Linh",
        40,
        (("Java", 5), ("Spring Boot", 5), ("PostgreSQL", 4), ("Docker", 3)),
    ),
    DemoStaff(
        "minh.phan@example.test",
        "Phan Tuấn Minh",
        36,
        (("Flutter", 5), ("TypeScript", 3), ("UI Design", 3), ("Test Automation", 3)),
    ),
    DemoStaff(
        "nam.do@example.test",
        "Đỗ Ngọc Nam",
        40,
        (("Manual Testing", 5), ("Business Analysis", 3), ("Playwright", 2), ("Agile/Scrum", 3)),
    ),
    DemoStaff(
        "nguyen.bui@example.test",
        "Bùi Thảo Nguyên",
        36,
        (("Test Automation", 5), ("Playwright", 5), ("TypeScript", 4), ("Python", 3)),
    ),
    DemoStaff(
        "phuc.ho@example.test",
        "Hồ Quang Phúc",
        40,
        (("DevOps", 5), ("Docker", 5), ("Kubernetes", 4), ("Cloud Infrastructure", 4)),
        leave_hours=16,
    ),
    DemoStaff(
        "quan.vu@example.test",
        "Vũ Bảo Quân",
        40,
        (("Data Engineering", 5), ("Python", 4), ("PostgreSQL", 5), ("Cloud Infrastructure", 3)),
    ),
    DemoStaff(
        "trang.dang@example.test",
        "Đặng Mai Trang",
        36,
        (("Machine Learning", 5), ("Python", 5), ("Data Engineering", 4), ("FastAPI", 3)),
    ),
    DemoStaff(
        "tu.ly@example.test",
        "Lý Anh Tú",
        40,
        (("Cybersecurity", 5), ("Networking", 4), ("Cloud Infrastructure", 3), ("Python", 3)),
    ),
    DemoStaff(
        "van.mai@example.test",
        "Mai Thanh Vân",
        32,
        (("IT Support", 5), ("Networking", 4), ("Cybersecurity", 3), ("Agile/Scrum", 2)),
    ),
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
) -> tuple[MembershipModel, bool]:
    membership = await session.scalar(
        select(MembershipModel).where(
            MembershipModel.organization_id == organization.id,
            MembershipModel.user_id == user.id,
        )
    )
    if membership is not None:
        membership.role = role
        membership.is_active = True
        return membership, False

    membership = MembershipModel(
        id=uuid4(),
        organization_id=organization.id,
        user_id=user.id,
        role=role,
        is_active=True,
    )
    session.add(membership)
    return membership, True


async def _get_or_create_skill(
    session: AsyncSession,
    organization_id: UUID,
    manager_membership_id: UUID,
    value: DemoSkill,
) -> SkillModel:
    normalized_name = " ".join(value.name.lower().split())
    skill = await session.scalar(
        select(SkillModel).where(
            SkillModel.organization_id == organization_id,
            SkillModel.normalized_name == normalized_name,
        )
    )
    if skill is not None:
        return skill
    skill = SkillModel(
        id=uuid4(),
        organization_id=organization_id,
        name=value.name,
        normalized_name=normalized_name,
        description=value.description,
        active=True,
        version=1,
        created_by_membership_id=manager_membership_id,
        updated_by_membership_id=manager_membership_id,
    )
    session.add(skill)
    session.add(
        SkillVersionModel(
            id=uuid4(),
            organization_id=organization_id,
            skill_id=skill.id,
            version=1,
            name=value.name,
            normalized_name=normalized_name,
            description=value.description,
            active=True,
            changed_by_membership_id=manager_membership_id,
        )
    )
    return skill


async def _get_or_create_person_skill(
    session: AsyncSession,
    organization_id: UUID,
    membership_id: UUID,
    skill: SkillModel,
    level: int,
    manager_membership_id: UUID,
) -> PersonSkillModel:
    person_skill = await session.scalar(
        select(PersonSkillModel).where(
            PersonSkillModel.organization_id == organization_id,
            PersonSkillModel.membership_id == membership_id,
            PersonSkillModel.skill_id == skill.id,
        )
    )
    if person_skill is not None:
        return person_skill
    person_skill = PersonSkillModel(
        id=uuid4(),
        organization_id=organization_id,
        membership_id=membership_id,
        skill_id=skill.id,
        level=level,
        verified_by_membership_id=manager_membership_id,
        verified_at=_VERIFIED_AT,
        active=True,
        version=1,
    )
    session.add(person_skill)
    return person_skill


async def _get_or_create_skill_evidence(
    session: AsyncSession,
    organization_id: UUID,
    person_skill: PersonSkillModel,
    staff: DemoStaff,
    skill: SkillModel,
    manager_membership_id: UUID,
) -> None:
    existing = await session.scalar(
        select(SkillEvidenceModel).where(
            SkillEvidenceModel.organization_id == organization_id,
            SkillEvidenceModel.person_skill_id == person_skill.id,
            SkillEvidenceModel.source_resource_type == "demo_profile",
        )
    )
    if existing is not None:
        return
    evidence_id = uuid5(
        _DEMO_NAMESPACE,
        f"evidence:{organization_id}:{staff.email}:{skill.normalized_name}",
    )
    session.add(
        SkillEvidenceModel(
            id=evidence_id,
            organization_id=organization_id,
            person_skill_id=person_skill.id,
            evidence_type=SkillEvidenceType.MANAGER_NOTE,
            summary=f"Verified demo evidence for {staff.display_name}: {skill.name}.",
            source_resource_type="demo_profile",
            source_resource_id=uuid5(
                _DEMO_NAMESPACE,
                f"source:{organization_id}:{staff.email}:{skill.normalized_name}",
            ),
            source_task_id=None,
            occurred_at=_VERIFIED_AT,
            created_by_membership_id=manager_membership_id,
        )
    )


async def _get_or_create_capacity(
    session: AsyncSession,
    organization_id: UUID,
    membership_id: UUID,
    hours: int,
) -> None:
    capacity = await session.scalar(
        select(CapacityEntryModel).where(
            CapacityEntryModel.organization_id == organization_id,
            CapacityEntryModel.membership_id == membership_id,
            CapacityEntryModel.kind == CapacityKind.DEFAULT,
        )
    )
    if capacity is not None:
        return
    session.add(
        CapacityEntryModel(
            id=uuid4(),
            organization_id=organization_id,
            membership_id=membership_id,
            kind=CapacityKind.DEFAULT,
            hours=hours,
            effective_from=date(2020, 1, 1),
            effective_to=date(2099, 12, 31),
            week_start=None,
            version=1,
        )
    )


async def _get_or_create_leave(
    session: AsyncSession,
    organization_id: UUID,
    membership_id: UUID,
    staff: DemoStaff,
) -> None:
    if staff.leave_hours == 0:
        return
    existing = await session.scalar(
        select(LeaveEntryModel).where(
            LeaveEntryModel.organization_id == organization_id,
            LeaveEntryModel.membership_id == membership_id,
            LeaveEntryModel.start_date == date(2026, 9, 21),
            LeaveEntryModel.end_date == date(2026, 9, 25),
        )
    )
    if existing is not None:
        return
    leave_id = uuid5(_DEMO_NAMESPACE, f"leave:{organization_id}:{staff.email}")
    session.add(
        LeaveEntryModel(
            id=leave_id,
            organization_id=organization_id,
            membership_id=membership_id,
            start_date=date(2026, 9, 21),
            end_date=date(2026, 9, 25),
            unavailable_hours=staff.leave_hours,
            version=1,
        )
    )


async def seed_demo_data(session: AsyncSession, settings: Settings) -> SeedResult:
    """Create or reconcile the fixed local demo records in one transaction."""

    password = settings.demo_seed_password.get_secret_value()
    organization, organization_created = await _get_or_create_organization(session, settings)
    users_created = 0
    memberships_created = 0
    seeded_user_ids: list[UUID] = []
    memberships_by_email: dict[str, MembershipModel] = {}

    accounts = (
        *DEMO_ACCOUNTS,
        *(
            DemoAccount(staff.email, staff.display_name, MembershipRole.EMPLOYEE)
            for staff in IT_STAFF
        ),
    )
    for account in accounts:
        user, was_created = await _get_or_create_user(session, account, password)
        seeded_user_ids.append(user.id)
        users_created += int(was_created)
        membership, membership_created = await _get_or_create_membership(
            session, organization, user, account.role
        )
        memberships_by_email[account.email] = membership
        memberships_created += int(membership_created)

    manager_membership_id = memberships_by_email["manager@example.test"].id
    skills_by_name = {
        value.name: await _get_or_create_skill(
            session, organization.id, manager_membership_id, value
        )
        for value in DEMO_SKILLS
    }
    # These models intentionally have no ORM relationships. Persist the catalog
    # before adding person-skill rows so foreign-key order is explicit for both
    # fresh and pre-existing organizations.
    await session.flush()
    for staff in IT_STAFF:
        membership_id = memberships_by_email[staff.email].id
        await _get_or_create_capacity(session, organization.id, membership_id, staff.capacity_hours)
        await _get_or_create_leave(session, organization.id, membership_id, staff)
        for skill_name, level in staff.skills:
            skill = skills_by_name[skill_name]
            person_skill = await _get_or_create_person_skill(
                session,
                organization.id,
                membership_id,
                skill,
                level,
                manager_membership_id,
            )
            await _get_or_create_skill_evidence(
                session,
                organization.id,
                person_skill,
                staff,
                skill,
                manager_membership_id,
            )

    await session.flush()
    membership_count = await session.scalar(
        select(func.count())
        .select_from(MembershipModel)
        .where(
            MembershipModel.organization_id == organization.id,
            MembershipModel.user_id.in_(seeded_user_ids),
        )
    )
    if membership_count != len(accounts):
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
