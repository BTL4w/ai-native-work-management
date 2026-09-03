"""Deterministic weekly workload calculation tests."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.people_capacity.domain.workload import (
    InvalidWorkloadInputError,
    WorkloadInput,
    calculate_weekly_workload,
)


def test_default_capacity_subtracts_partial_leave_and_open_task_effort() -> None:
    membership_id, project_week_id = uuid4(), uuid4()

    result = calculate_weekly_workload(
        WorkloadInput(
            membership_id=membership_id,
            project_week_id=project_week_id,
            default_capacity_hours=40,
            override_capacity_hours=None,
            leave_hours=8,
            open_task_effort_hours=(10, 6),
        )
    )

    assert result.membership_id == membership_id
    assert result.project_week_id == project_week_id
    assert result.effective_capacity_hours == 32
    assert result.allocated_effort_hours == 16
    assert result.residual_capacity_hours == 16
    assert result.workload_ratio == Decimal("0.5")


def test_weekly_override_takes_precedence_over_default_capacity() -> None:
    result = calculate_weekly_workload(
        WorkloadInput(
            membership_id=uuid4(),
            project_week_id=uuid4(),
            default_capacity_hours=40,
            override_capacity_hours=20,
            leave_hours=4,
            open_task_effort_hours=(8,),
        )
    )

    assert result.effective_capacity_hours == 16
    assert result.residual_capacity_hours == 8
    assert result.workload_ratio == Decimal("0.5")


def test_full_leave_clamps_capacity_to_zero_and_ratio_is_unknown() -> None:
    result = calculate_weekly_workload(
        WorkloadInput(
            membership_id=uuid4(),
            project_week_id=uuid4(),
            default_capacity_hours=40,
            override_capacity_hours=None,
            leave_hours=48,
            open_task_effort_hours=(8,),
        )
    )

    assert result.effective_capacity_hours == 0
    assert result.allocated_effort_hours == 8
    assert result.residual_capacity_hours == 0
    assert result.workload_ratio is None


def test_overallocation_keeps_exact_ratio_and_clamps_residual_to_zero() -> None:
    result = calculate_weekly_workload(
        WorkloadInput(
            membership_id=uuid4(),
            project_week_id=uuid4(),
            default_capacity_hours=40,
            override_capacity_hours=None,
            leave_hours=0,
            open_task_effort_hours=(30, 20),
        )
    )

    assert result.allocated_effort_hours == 50
    assert result.residual_capacity_hours == 0
    assert result.workload_ratio == Decimal("1.25")


def test_only_prefiltered_open_task_effort_is_allocated() -> None:
    result = calculate_weekly_workload(
        WorkloadInput(
            membership_id=uuid4(),
            project_week_id=uuid4(),
            default_capacity_hours=40,
            override_capacity_hours=None,
            leave_hours=0,
            # The Task source excludes DONE rows before constructing this tuple.
            open_task_effort_hours=(7, 5),
        )
    )

    assert result.allocated_effort_hours == 12


def test_workload_input_copies_mutable_effort_collections() -> None:
    efforts = [8]
    value = WorkloadInput(
        membership_id=uuid4(),
        project_week_id=uuid4(),
        default_capacity_hours=40,
        override_capacity_hours=None,
        leave_hours=0,
        open_task_effort_hours=efforts,  # type: ignore[arg-type]
    )

    efforts.append(16)

    assert value.open_task_effort_hours == (8,)
    assert calculate_weekly_workload(value).allocated_effort_hours == 8


@pytest.mark.parametrize("hours", [0, 168])
def test_weekly_hour_boundaries_are_accepted(hours: int) -> None:
    value = WorkloadInput(
        membership_id=uuid4(),
        project_week_id=uuid4(),
        default_capacity_hours=hours,
        override_capacity_hours=hours,
        leave_hours=hours,
        open_task_effort_hours=(1,),
    )

    assert value.default_capacity_hours == hours


@pytest.mark.parametrize("field", ["default", "override", "leave"])
@pytest.mark.parametrize("invalid", [-1, 169, 1.5, True])
def test_weekly_capacity_and_leave_hours_are_integers_between_zero_and_168(
    field: str, invalid: object
) -> None:
    values: dict[str, object] = {
        "default_capacity_hours": 40,
        "override_capacity_hours": None,
        "leave_hours": 8,
        "open_task_effort_hours": (12,),
    }
    target = {
        "default": "default_capacity_hours",
        "override": "override_capacity_hours",
        "leave": "leave_hours",
        "task": "open_task_effort_hours",
    }[field]
    values[target] = invalid

    with pytest.raises(InvalidWorkloadInputError, match=target):
        WorkloadInput(
            membership_id=uuid4(),
            project_week_id=uuid4(),
            **values,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("effort", [169, 10_000])
def test_task_effort_uses_the_authoritative_task_domain_limit(effort: int) -> None:
    result = calculate_weekly_workload(
        WorkloadInput(
            membership_id=uuid4(),
            project_week_id=uuid4(),
            default_capacity_hours=40,
            override_capacity_hours=None,
            leave_hours=0,
            open_task_effort_hours=(effort,),
        )
    )

    assert result.allocated_effort_hours == effort
    assert result.workload_ratio == Decimal(effort) / Decimal(40)


@pytest.mark.parametrize("invalid", [0, 10_001, 1.5, True])
def test_task_effort_matches_existing_task_validation(invalid: object) -> None:
    with pytest.raises(InvalidWorkloadInputError, match="open_task_effort_hours"):
        WorkloadInput(
            membership_id=uuid4(),
            project_week_id=uuid4(),
            default_capacity_hours=40,
            override_capacity_hours=None,
            leave_hours=0,
            open_task_effort_hours=(invalid,),  # type: ignore[arg-type]
        )
