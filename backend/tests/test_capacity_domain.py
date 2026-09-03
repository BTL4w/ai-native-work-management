"""Boundary tests for immutable capacity and leave values."""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.modules.people_capacity.domain.availability import (
    CapacityEntryDraft,
    CapacityKind,
    InvalidCapacityEntryError,
    InvalidLeaveEntryError,
    LeaveEntryDraft,
    OverlappingCapacityEntriesError,
    ensure_capacity_entry_does_not_overlap,
)


def test_capacity_draft_accepts_default_and_weekly_override_ranges() -> None:
    membership_id = uuid4()
    default = CapacityEntryDraft.create(
        membership_id=membership_id,
        kind="DEFAULT",
        hours=40,
        effective_from=date(2026, 9, 1),
        effective_to=date(2026, 12, 31),
        week_start=None,
    )
    override = CapacityEntryDraft.create(
        membership_id=membership_id,
        kind="OVERRIDE",
        hours=24,
        effective_from=date(2026, 9, 7),
        effective_to=date(2026, 9, 13),
        week_start=date(2026, 9, 7),
        project_week_end=date(2026, 9, 13),
    )

    assert default.kind is CapacityKind.DEFAULT
    assert override.kind is CapacityKind.OVERRIDE
    assert override.week_start == override.effective_from
    with pytest.raises(FrozenInstanceError):
        override.hours = 32  # type: ignore[misc]


@pytest.mark.parametrize("hours", [-1, 169, 1.5, True])
def test_capacity_hours_must_be_integer_between_zero_and_168(hours: object) -> None:
    with pytest.raises(InvalidCapacityEntryError, match="hours"):
        CapacityEntryDraft.create(
            membership_id=uuid4(),
            kind="DEFAULT",
            hours=hours,  # type: ignore[arg-type]
            effective_from=date(2026, 9, 1),
            effective_to=date(2026, 9, 30),
            week_start=None,
        )


def test_capacity_kind_controls_week_start_and_range_alignment() -> None:
    with pytest.raises(InvalidCapacityEntryError, match="week_start"):
        CapacityEntryDraft.create(
            membership_id=uuid4(),
            kind="DEFAULT",
            hours=40,
            effective_from=date(2026, 9, 1),
            effective_to=date(2026, 9, 30),
            week_start=date(2026, 9, 1),
        )
    with pytest.raises(InvalidCapacityEntryError, match="week_start"):
        CapacityEntryDraft.create(
            membership_id=uuid4(),
            kind="OVERRIDE",
            hours=32,
            effective_from=date(2026, 9, 8),
            effective_to=date(2026, 9, 13),
            week_start=date(2026, 9, 7),
            project_week_end=date(2026, 9, 13),
        )


def test_override_range_must_match_resolved_project_week_end() -> None:
    with pytest.raises(InvalidCapacityEntryError, match="effective_date_range"):
        CapacityEntryDraft.create(
            membership_id=uuid4(),
            kind="OVERRIDE",
            hours=32,
            effective_from=date(2026, 9, 7),
            effective_to=date(2026, 9, 12),
            week_start=date(2026, 9, 7),
            project_week_end=date(2026, 9, 13),
        )


def test_capacity_rejects_reversed_effective_range() -> None:
    with pytest.raises(InvalidCapacityEntryError, match="effective_date_range"):
        CapacityEntryDraft.create(
            membership_id=uuid4(),
            kind="DEFAULT",
            hours=40,
            effective_from=date(2026, 9, 30),
            effective_to=date(2026, 9, 1),
            week_start=None,
        )


def test_same_member_and_kind_cannot_have_overlapping_effective_ranges() -> None:
    membership_id = uuid4()
    existing = CapacityEntryDraft.create(
        membership_id=membership_id,
        kind="DEFAULT",
        hours=40,
        effective_from=date(2026, 9, 1),
        effective_to=date(2026, 9, 30),
        week_start=None,
    )
    overlapping = CapacityEntryDraft.create(
        membership_id=membership_id,
        kind="DEFAULT",
        hours=32,
        effective_from=date(2026, 9, 30),
        effective_to=date(2026, 10, 31),
        week_start=None,
    )

    with pytest.raises(OverlappingCapacityEntriesError):
        ensure_capacity_entry_does_not_overlap(overlapping, (existing,))


def test_overlap_check_allows_other_members_kinds_and_adjacent_ranges() -> None:
    membership_id = uuid4()
    candidate = CapacityEntryDraft.create(
        membership_id=membership_id,
        kind="DEFAULT",
        hours=40,
        effective_from=date(2026, 10, 1),
        effective_to=date(2026, 10, 31),
        week_start=None,
    )
    allowed = (
        CapacityEntryDraft.create(
            membership_id=membership_id,
            kind="DEFAULT",
            hours=40,
            effective_from=date(2026, 9, 1),
            effective_to=date(2026, 9, 30),
            week_start=None,
        ),
        CapacityEntryDraft.create(
            membership_id=membership_id,
            kind="OVERRIDE",
            hours=24,
            effective_from=date(2026, 10, 5),
            effective_to=date(2026, 10, 11),
            week_start=date(2026, 10, 5),
            project_week_end=date(2026, 10, 11),
        ),
        CapacityEntryDraft.create(
            membership_id=uuid4(),
            kind="DEFAULT",
            hours=32,
            effective_from=date(2026, 10, 1),
            effective_to=date(2026, 10, 31),
            week_start=None,
        ),
    )

    ensure_capacity_entry_does_not_overlap(candidate, allowed)


def test_overlapping_weekly_overrides_are_rejected() -> None:
    membership_id = uuid4()
    existing = CapacityEntryDraft.create(
        membership_id=membership_id,
        kind="OVERRIDE",
        hours=32,
        effective_from=date(2026, 9, 7),
        effective_to=date(2026, 9, 13),
        week_start=date(2026, 9, 7),
        project_week_end=date(2026, 9, 13),
    )
    duplicate = CapacityEntryDraft.create(
        membership_id=membership_id,
        kind="OVERRIDE",
        hours=24,
        effective_from=date(2026, 9, 7),
        effective_to=date(2026, 9, 13),
        week_start=date(2026, 9, 7),
        project_week_end=date(2026, 9, 13),
    )

    with pytest.raises(OverlappingCapacityEntriesError):
        ensure_capacity_entry_does_not_overlap(duplicate, (existing,))


def test_leave_accepts_partial_and_full_week_unavailability() -> None:
    membership_id = uuid4()
    partial = LeaveEntryDraft.create(
        membership_id=membership_id,
        start_date=date(2026, 9, 8),
        end_date=date(2026, 9, 8),
        unavailable_hours=8,
    )
    full = LeaveEntryDraft.create(
        membership_id=membership_id,
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 13),
        unavailable_hours=40,
    )

    assert partial.unavailable_hours == 8
    assert full.unavailable_hours == 40


@pytest.mark.parametrize("hours", [-1, 169, 2.5, False])
def test_leave_hours_must_be_integer_between_zero_and_168(hours: object) -> None:
    with pytest.raises(InvalidLeaveEntryError, match="unavailable_hours"):
        LeaveEntryDraft.create(
            membership_id=uuid4(),
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 13),
            unavailable_hours=hours,  # type: ignore[arg-type]
        )


def test_leave_rejects_reversed_inclusive_range() -> None:
    with pytest.raises(InvalidLeaveEntryError, match="date_range"):
        LeaveEntryDraft.create(
            membership_id=uuid4(),
            start_date=date(2026, 9, 13),
            end_date=date(2026, 9, 7),
            unavailable_hours=8,
        )


def test_capacity_and_leave_reject_datetime_values_as_calendar_dates() -> None:
    timestamp = datetime(2026, 9, 7, tzinfo=UTC)
    with pytest.raises(InvalidCapacityEntryError, match="effective_from"):
        CapacityEntryDraft.create(
            membership_id=uuid4(),
            kind="DEFAULT",
            hours=40,
            effective_from=timestamp,  # type: ignore[arg-type]
            effective_to=date(2026, 9, 30),
            week_start=None,
        )
    with pytest.raises(InvalidLeaveEntryError, match="start_date"):
        LeaveEntryDraft.create(
            membership_id=uuid4(),
            start_date=timestamp,  # type: ignore[arg-type]
            end_date=date(2026, 9, 13),
            unavailable_hours=8,
        )
