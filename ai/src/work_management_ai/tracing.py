"""Redacted, non-blocking tracing boundary for AI workflows."""

import logging
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TraceMetadata:
    """Safe metadata only; prompts, provider errors and reasoning are excluded."""

    run_id: UUID
    node: str
    outcome: Literal["STARTED", "COMPLETED", "INTERRUPTED", "FAILED"]
    workflow_version: str
    prompt_version: str
    schema_version: str
    verifier_version: str
    model_reference: str | None = None
    error_code: str | None = None


class TracePort(Protocol):
    """Optional observational sink that cannot affect workflow decisions."""

    async def record(self, metadata: TraceMetadata) -> None: ...


class NoopTracePort:
    """Default trace adapter for local and automated execution."""

    async def record(self, metadata: TraceMetadata) -> None:
        del metadata


async def record_safely(port: TracePort, metadata: TraceMetadata) -> None:
    """Isolate tracing/LangSmith outages without logging sensitive details."""

    try:
        await port.record(metadata)
    except Exception:
        logger.warning(
            "AI trace sink failed for run=%s node=%s",
            metadata.run_id,
            metadata.node,
        )
