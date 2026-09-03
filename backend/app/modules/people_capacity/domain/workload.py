"""Pure deterministic weekly workload calculation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


class InvalidWorkloadInputError(Exception):
    """A workload input violates its deterministic hour boundary."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


def _hours(value: int, *, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 168:
        raise InvalidWorkloadInputError(field)
    return value


def _task_effort(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 10_000:
        raise InvalidWorkloadInputError("open_task_effort_hours")
    return value


@dataclass(frozen=True, slots=True)
class WorkloadInput:
    """Resolved inputs for one member in one Project Week."""

    membership_id: UUID
    project_week_id: UUID
    default_capacity_hours: int
    override_capacity_hours: int | None
    leave_hours: int
    open_task_effort_hours: tuple[int, ...]

    def __post_init__(self) -> None:
        efforts = tuple(self.open_task_effort_hours)
        object.__setattr__(self, "open_task_effort_hours", efforts)
        _hours(self.default_capacity_hours, field="default_capacity_hours")
        if self.override_capacity_hours is not None:
            _hours(self.override_capacity_hours, field="override_capacity_hours")
        _hours(self.leave_hours, field="leave_hours")
        for effort in efforts:
            _task_effort(effort)


@dataclass(frozen=True, slots=True)
class WeeklyWorkload:
    """Calculated capacity and allocation for one member and Project Week."""

    membership_id: UUID
    project_week_id: UUID
    effective_capacity_hours: int
    allocated_effort_hours: int
    residual_capacity_hours: int
    workload_ratio: Decimal | None


def calculate_weekly_workload(value: WorkloadInput) -> WeeklyWorkload:
    """Calculate workload without model input, I/O, or persisted derived state."""

    capacity = (
        value.override_capacity_hours
        if value.override_capacity_hours is not None
        else value.default_capacity_hours
    )
    effective = max(capacity - value.leave_hours, 0)
    allocated = sum(value.open_task_effort_hours)
    residual = max(effective - allocated, 0)
    ratio = None if effective == 0 else Decimal(allocated) / Decimal(effective)
    return WeeklyWorkload(
        membership_id=value.membership_id,
        project_week_id=value.project_week_id,
        effective_capacity_hours=effective,
        allocated_effort_hours=allocated,
        residual_capacity_hours=residual,
        workload_ratio=ratio,
    )
