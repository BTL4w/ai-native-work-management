"""SQLAlchemy read adapter for tenant-scoped member lookup."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity.adapters.database_models import UserModel
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.adapters.database_models import MembershipModel
from app.modules.organization.application.member_service import (
    MemberPage,
    MemberRepository,
    MemberSummary,
)
from app.modules.organization.domain.roles import MembershipRole


class SqlAlchemyMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_members(
        self,
        *,
        actor: AuthenticatedActor,
        query: str | None,
        role: MembershipRole | None,
        is_active: bool | None,
        page: int,
        page_size: int,
    ) -> MemberPage:
        await self._session.execute(text("SET LOCAL ROLE app_runtime"))
        await self._session.execute(
            text("SELECT set_config('app.organization_id', :value, true)"),
            {"value": str(actor.organization_id)},
        )
        predicates = [MembershipModel.organization_id == actor.organization_id]
        if query:
            predicates.append(or_(UserModel.display_name.ilike(f"%{query}%")))
        if role is not None:
            predicates.append(MembershipModel.role == role)
        if is_active is not None:
            predicates.append(MembershipModel.is_active.is_(is_active))
        base = (
            select(MembershipModel, UserModel.display_name)
            .join(UserModel, UserModel.id == MembershipModel.user_id)
            .where(*predicates)
        )
        total = await self._session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = (
            await self._session.execute(
                base.order_by(UserModel.display_name, MembershipModel.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return MemberPage(
            items=tuple(
                MemberSummary(
                    membership_id=m.id, display_name=name, role=m.role, is_active=m.is_active
                )
                for m, name in rows
            ),
            page=page,
            page_size=page_size,
            total=total,
        )


class SqlAlchemyMemberTransactionFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[MemberRepository]:
        async with self._sessions.begin() as session:
            yield SqlAlchemyMemberRepository(session)
