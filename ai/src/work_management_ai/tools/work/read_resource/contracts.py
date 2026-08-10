"""Discriminated contracts for permission-safe resource resolution."""

from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel

from work_management_ai.agents.work_intelligence.contracts import EvidenceItem
from work_management_ai.runtime.contracts import ActorReference, JsonValue


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ProjectRequest(_StrictFrozenModel):
    resource_type: Literal["PROJECT"]
    reference: str = Field(min_length=1, max_length=300)


class _TaskRequest(_StrictFrozenModel):
    resource_type: Literal["TASK"]
    reference: str = Field(min_length=1, max_length=300)


class _DependencyRequest(_StrictFrozenModel):
    resource_type: Literal["DEPENDENCY"]
    reference: str = Field(min_length=1, max_length=300)


class _CriterionRequest(_StrictFrozenModel):
    resource_type: Literal["ACCEPTANCE_CRITERION"]
    reference: str = Field(min_length=1, max_length=300)


type ResourceRequest = Annotated[
    _ProjectRequest | _TaskRequest | _DependencyRequest | _CriterionRequest,
    Field(discriminator="resource_type"),
]


class ReadResourceInput(RootModel[ResourceRequest]):
    model_config = ConfigDict(frozen=True)


class ResourceReadRecord(_StrictFrozenModel):
    resource_type: Literal["PROJECT", "TASK", "DEPENDENCY", "ACCEPTANCE_CRITERION"]
    resource_id: UUID
    resource_version: int | None = Field(default=None, ge=1)
    fields: dict[str, JsonValue]
    observed_at: datetime


class ResourceResolution(_StrictFrozenModel):
    status: Literal["UNIQUE", "AMBIGUOUS", "NOT_FOUND"]
    records: tuple[ResourceReadRecord, ...] = ()


class ReadResourceOutput(_StrictFrozenModel):
    resolution: Literal["UNIQUE", "AMBIGUOUS", "NOT_FOUND"]
    evidence: tuple[EvidenceItem, ...]
    next_task_id: None = None


class ReadResourceApplicationPort(Protocol):
    async def resolve_resource(
        self, *, actor: ActorReference, value: ReadResourceInput
    ) -> ResourceResolution: ...
