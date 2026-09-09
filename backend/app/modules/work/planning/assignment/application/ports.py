"""Ports for transaction-scoped team requirement persistence."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from app.modules.work.planning.assignment.application.requirement_service import (
    ConfirmRequirementsCommand,
    DeriveRequirementsCommand,
    RequirementSet,
    ReviseRequirementsCommand,
)


class TeamRequirementRepository(Protocol):
    async def derive(self, command: DeriveRequirementsCommand) -> RequirementSet: ...
    async def revise(self, command: ReviseRequirementsCommand) -> RequirementSet: ...
    async def confirm(self, command: ConfirmRequirementsCommand) -> RequirementSet: ...
    async def get_for_project(
        self, *, actor: object, project_id: object
    ) -> RequirementSet | None: ...
    async def audit_rejection(
        self,
        *,
        actor: object,
        action: str,
        request_id: str,
        idempotency_key: str | None,
        resource_id: object | None,
        reason_code: str,
    ) -> None: ...


TeamRequirementTransactionFactory = Callable[
    [], AbstractAsyncContextManager[TeamRequirementRepository]
]
