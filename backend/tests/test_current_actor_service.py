# pyright: reportUnknownParameterType=false, reportMissingParameterType=false

from uuid import uuid4

import pytest

from app.modules.identity.application.current_actor_service import CurrentActorService
from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole


class Repo:
    def __init__(self, actor):
        self.actor = actor

    async def find_current_actor_by_membership(self, **kwargs):
        return self.actor


class Txn:
    def __init__(self, repo):
        self.repo = repo

    async def __aenter__(self):
        return self.repo

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_current_actor_service_fails_closed_on_cross_tenant_actor() -> None:
    organization_id, other = uuid4(), uuid4()
    actor = AuthenticatedActor(
        uuid4(), "a@example.test", "A", uuid4(), other, "Other", MembershipRole.MANAGER
    )
    service = CurrentActorService(lambda: Txn(Repo(actor)))  # type: ignore[arg-type]
    assert (
        await service.resolve(organization_id=organization_id, membership_id=actor.membership_id)
        is None
    )
