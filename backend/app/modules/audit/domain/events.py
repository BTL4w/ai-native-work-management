"""Stable audit outcomes."""

from enum import StrEnum


class AuditOutcome(StrEnum):
    """Whether an audited action completed or was rejected."""

    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
