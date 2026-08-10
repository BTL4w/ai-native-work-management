"""Read-resource Tool."""

from work_management_ai.tools.work.read_resource.adapter import ReadResourceToolAdapter
from work_management_ai.tools.work.read_resource.contracts import (
    ReadResourceInput,
    ReadResourceOutput,
    ResourceReadRecord,
    ResourceResolution,
)

__all__ = [
    "ReadResourceInput",
    "ReadResourceOutput",
    "ReadResourceToolAdapter",
    "ResourceReadRecord",
    "ResourceResolution",
]
