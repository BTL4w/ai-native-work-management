"""Replayable, sanitized workflow event streaming with short transactions."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import cast
from uuid import UUID

from app.modules.identity.domain.auth import AuthenticatedActor
from app.modules.organization.domain.roles import MembershipRole
from app.modules.planning_runs.application.ports import PlanningRunTransaction
from app.modules.planning_runs.domain.models import (
    PlanningRunForbiddenError,
    PlanningRunNotFoundError,
    WorkflowEvent,
    WorkflowRun,
)

_READ_ROLES = frozenset({MembershipRole.ADMIN, MembershipRole.MANAGER})
_SENSITIVE_KEYS = (
    "prompt",
    "secret",
    "token",
    "reasoning",
    "chain_of_thought",
    "stack",
    "provider_error",
)


def _sanitize(value: object) -> object:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            str(key): _sanitize(item)
            for key, item in mapping.items()
            if not any(part in str(key).casefold() for part in _SENSITIVE_KEYS)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in cast(list[object] | tuple[object, ...], value)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _frame(event: WorkflowEvent) -> str:
    payload = json.dumps(
        _sanitize(event.public_payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"


class WorkflowEventService:
    def __init__(
        self,
        *,
        transaction_factory: Callable[[AuthenticatedActor], PlanningRunTransaction],
        heartbeat_seconds: float = 15,
    ) -> None:
        self._transaction_factory = transaction_factory
        self._heartbeat_seconds = heartbeat_seconds

    async def authorize(self, *, actor: AuthenticatedActor, run_id: UUID) -> WorkflowRun:
        if actor.role not in _READ_ROLES:
            raise PlanningRunForbiddenError
        async with self._transaction_factory(actor) as transaction:
            run = await transaction.repository.get_workflow_run(actor=actor, run_id=run_id)
        if run is None:
            raise PlanningRunNotFoundError
        return run

    async def _read(
        self, *, actor: AuthenticatedActor, run_id: UUID, after_sequence: int
    ) -> tuple[WorkflowRun, list[WorkflowEvent]]:
        async with self._transaction_factory(actor) as transaction:
            run = await transaction.repository.get_workflow_run(actor=actor, run_id=run_id)
            if run is None:
                raise PlanningRunNotFoundError
            events = await transaction.repository.list_events(
                actor=actor,
                run_id=run_id,
                after_sequence=after_sequence,
            )
        return run, events

    async def replay(
        self, *, actor: AuthenticatedActor, run_id: UUID, after_sequence: int
    ) -> list[str]:
        if actor.role not in _READ_ROLES:
            raise PlanningRunForbiddenError
        _, events = await self._read(actor=actor, run_id=run_id, after_sequence=after_sequence)
        return [_frame(event) for event in events]

    async def stream(
        self, *, actor: AuthenticatedActor, run_id: UUID, after_sequence: int
    ) -> AsyncIterator[str]:
        cursor = after_sequence
        while True:
            run, events = await self._read(actor=actor, run_id=run_id, after_sequence=cursor)
            for event in events:
                cursor = event.sequence
                yield _frame(event)
            if run.status.is_terminal:
                return
            if not events:
                yield ": heartbeat\n\n"
            await asyncio.sleep(self._heartbeat_seconds)
