"""Safe structured checkpoint memory without authority or hidden reasoning."""

from copy import deepcopy

from pydantic import BaseModel, ConfigDict, TypeAdapter

from work_management_ai.runtime.contracts import JsonValue

_RESERVED_MEMORY_KEYS = frozenset(
    {
        "hidden_reasoning",
        "chain_of_thought",
        "organization_id",
        "tenant_id",
        "role",
        "permissions",
        "allowed_tools",
        "approved",
        "approval_id",
    }
)
_JSON_ADAPTER = TypeAdapter(dict[str, JsonValue])


class RuntimeMemoryError(ValueError):
    pass


class RuntimeCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: dict[str, JsonValue]


class MemoryManager:
    def checkpoint(self, state: dict[str, JsonValue]) -> RuntimeCheckpoint:
        self._reject_reserved_keys(state)
        try:
            validated = _JSON_ADAPTER.validate_python(deepcopy(state))
        except ValueError as exc:
            raise RuntimeMemoryError("CHECKPOINT_STATE_INVALID") from exc
        return RuntimeCheckpoint(state=validated)

    @classmethod
    def _reject_reserved_keys(cls, value: JsonValue) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _RESERVED_MEMORY_KEYS:
                    raise RuntimeMemoryError("RESERVED_MEMORY_KEY")
                cls._reject_reserved_keys(child)
        elif isinstance(value, list):
            for child in value:
                cls._reject_reserved_keys(child)
