"""Bounded selection of explicit, tenant-scoped runtime context."""

from pydantic import BaseModel, ConfigDict

from work_management_ai.runtime.contracts import ActorReference, ContextReference


class ContextSelectionError(ValueError):
    pass


class SelectedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    references: tuple[ContextReference, ...]
    recent_messages: tuple[str, ...]


class ContextManager:
    def __init__(self, *, max_references: int = 32, max_recent_messages: int = 12) -> None:
        if not 1 <= max_references <= 128 or not 0 <= max_recent_messages <= 64:
            raise ValueError("context limits are out of bounds")
        self._max_references = max_references
        self._max_recent_messages = max_recent_messages

    def select(
        self,
        *,
        actor: ActorReference,
        references: tuple[ContextReference, ...],
        recent_messages: tuple[str, ...],
    ) -> SelectedContext:
        if any(reference.organization_id != actor.organization_id for reference in references):
            raise ContextSelectionError("CONTEXT_TENANT_MISMATCH")
        messages = (
            recent_messages[-self._max_recent_messages :] if self._max_recent_messages else ()
        )
        return SelectedContext(
            references=references[: self._max_references],
            recent_messages=messages,
        )
