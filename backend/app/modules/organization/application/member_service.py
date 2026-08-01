"""Read-only member lookup used by Phase 1 assignment."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole


class MemberForbiddenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class MemberSummary:
    membership_id: UUID
    display_name: str
    role: MembershipRole
    is_active: bool


@dataclass(frozen=True, slots=True)
class MemberPage:
    items: tuple[MemberSummary, ...]
    page: int
    page_size: int
    total: int


class MemberRepository(Protocol):
    async def list_members(
        self,
        *,
        actor: AuthenticatedActor,
        query: str | None,
        role: MembershipRole | None,
        is_active: bool | None,
        page: int,
        page_size: int,
    ) -> MemberPage: ...


MemberTransactionFactory = Callable[[], AbstractAsyncContextManager[MemberRepository]]


class MemberService:
    def __init__(self, transaction_factory: MemberTransactionFactory) -> None:
        self._transactions = transaction_factory

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
        if actor.role is MembershipRole.EMPLOYEE:
            raise MemberForbiddenError
        async with self._transactions() as repository:
            return await repository.list_members(
                actor=actor,
                query=query.strip() if query else None,
                role=role,
                is_active=is_active,
                page=page,
                page_size=page_size,
            )
