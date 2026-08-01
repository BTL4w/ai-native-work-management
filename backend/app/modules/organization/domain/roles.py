"""Organization membership roles used by Phase 1 authorization."""

from enum import StrEnum


class MembershipRole(StrEnum):
    """Fixed Phase 1 roles; ADMIN has Manager-equivalent work permissions."""

    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"
