"""Typed boundary for loading only permitted planning context."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PlanningContextRequest:
    run_id: UUID
    organization_id: UUID
    actor_membership_id: UUID
    locale: Literal["vi", "en"]
    user_brief: str
    manager_answers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PermittedPlanningContext:
    """Permission-filtered facts and provenance returned by the backend boundary."""

    reference_ids: tuple[str, ...]
    active_membership_ids: frozenset[UUID]
    required_questions: tuple[str, ...]
    structured_facts: dict[str, object]


class PlanningContextPort(Protocol):
    async def load_permitted_context(
        self,
        request: PlanningContextRequest,
    ) -> PermittedPlanningContext: ...
