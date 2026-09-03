"""Workload application service and data-loading protocol."""

from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.people_capacity.domain.workload import (
    WeeklyWorkload,
    WorkloadInput,
    calculate_weekly_workload,
)


class WorkloadSource(Protocol):
    """Authoritative source for resolving raw capacity, leave, and task effort."""

    async def load_workload_inputs(
        self,
        *,
        actor: AuthenticatedActor,
        week_start: date,
        membership_id: UUID | None,
    ) -> tuple[WorkloadInput, ...]: ...


class WorkloadService:
    """Computes deterministic weekly workload projections from verified inputs."""

    def __init__(self, workload_source: WorkloadSource) -> None:
        self._workload_source = workload_source

    async def list_weekly_workload(
        self,
        *,
        actor: AuthenticatedActor,
        week_start: date,
        membership_id: UUID | None,
    ) -> tuple[WeeklyWorkload, ...]:
        inputs = await self._workload_source.load_workload_inputs(
            actor=actor,
            week_start=week_start,
            membership_id=membership_id,
        )
        return tuple(calculate_weekly_workload(item) for item in inputs)
