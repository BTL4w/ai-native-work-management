"""Unit tests for the WorkloadService application boundary."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.people_capacity.application.workload_service import (
    WorkloadService,
)
from app.modules.people_capacity.domain.skills import PeopleSkillNotFoundError
from app.modules.people_capacity.domain.workload import (
    WorkloadInput,
)


def _actor(role: MembershipRole = MembershipRole.MANAGER) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid4(),
        email="manager@example.test",
        display_name="Test Manager",
        membership_id=uuid4(),
        organization_id=uuid4(),
        organization_name="Test Tenant",
        role=role,
    )


class FakeWorkloadSource:
    def __init__(self) -> None:
        self.inputs: list[WorkloadInput] = []
        self.active_memberships: set[UUID] = set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def load_workload_inputs(
        self,
        *,
        actor: AuthenticatedActor,
        week_start: date,
        membership_id: UUID | None,
    ) -> tuple[WorkloadInput, ...]:
        self.calls.append(
            (
                "load_workload_inputs",
                {
                    "actor": actor,
                    "week_start": week_start,
                    "membership_id": membership_id,
                },
            )
        )
        if membership_id is not None and membership_id not in self.active_memberships:
            raise PeopleSkillNotFoundError
        if membership_id is not None:
            return tuple(item for item in self.inputs if item.membership_id == membership_id)
        return tuple(self.inputs)


@pytest.mark.asyncio
async def test_workload_service_calculates_deterministic_weekly_projections() -> None:
    source = FakeWorkloadSource()
    service = WorkloadService(source)
    actor = _actor()
    member_id = uuid4()
    project_week_id = uuid4()
    source.active_memberships.add(member_id)
    source.inputs.append(
        WorkloadInput(
            membership_id=member_id,
            project_week_id=project_week_id,
            default_capacity_hours=40,
            override_capacity_hours=None,
            leave_hours=8,
            open_task_effort_hours=(12, 8),
        )
    )

    result = await service.list_weekly_workload(
        actor=actor,
        week_start=date(2026, 9, 7),
        membership_id=member_id,
    )

    assert len(result) == 1
    workload = result[0]
    assert workload.membership_id == member_id
    assert workload.project_week_id == project_week_id
    assert workload.effective_capacity_hours == 32
    assert workload.allocated_effort_hours == 20
    assert workload.residual_capacity_hours == 12
    assert workload.workload_ratio == Decimal("0.625")


@pytest.mark.asyncio
async def test_workload_service_override_precedence_and_zero_capacity_ratio() -> None:
    source = FakeWorkloadSource()
    service = WorkloadService(source)
    actor = _actor()
    member_id = uuid4()
    project_week_id = uuid4()
    source.active_memberships.add(member_id)
    source.inputs.append(
        WorkloadInput(
            membership_id=member_id,
            project_week_id=project_week_id,
            default_capacity_hours=40,
            override_capacity_hours=20,
            leave_hours=20,
            open_task_effort_hours=(10,),
        )
    )

    result = await service.list_weekly_workload(
        actor=actor,
        week_start=date(2026, 9, 7),
        membership_id=member_id,
    )

    assert len(result) == 1
    workload = result[0]
    assert workload.effective_capacity_hours == 0
    assert workload.allocated_effort_hours == 10
    assert workload.residual_capacity_hours == 0
    assert workload.workload_ratio is None


@pytest.mark.asyncio
async def test_workload_service_raises_not_found_for_unknown_member() -> None:
    source = FakeWorkloadSource()
    service = WorkloadService(source)
    actor = _actor()

    with pytest.raises(PeopleSkillNotFoundError):
        await service.list_weekly_workload(
            actor=actor,
            week_start=date(2026, 9, 7),
            membership_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_workload_service_queries_all_members_when_membership_id_is_none() -> None:
    source = FakeWorkloadSource()
    service = WorkloadService(source)
    actor = _actor()
    m1, m2 = uuid4(), uuid4()
    pw1 = uuid4()
    source.inputs.extend(
        [
            WorkloadInput(
                membership_id=m1,
                project_week_id=pw1,
                default_capacity_hours=40,
                override_capacity_hours=None,
                leave_hours=0,
                open_task_effort_hours=(5,),
            ),
            WorkloadInput(
                membership_id=m2,
                project_week_id=pw1,
                default_capacity_hours=35,
                override_capacity_hours=None,
                leave_hours=0,
                open_task_effort_hours=(),
            ),
        ]
    )

    result = await service.list_weekly_workload(
        actor=actor,
        week_start=date(2026, 9, 7),
        membership_id=None,
    )

    assert len(result) == 2
    assert {w.membership_id for w in result} == {m1, m2}
