"""Policy tests for the explicit local demo seed command."""

import pytest

from app.core.config import Settings
from app.modules.organization.domain.roles import MembershipRole
from app.scripts.seed_demo import DEMO_ACCOUNTS, ensure_demo_seed_allowed


def test_demo_personas_match_phase_one_roles() -> None:
    assert [(account.email, account.role) for account in DEMO_ACCOUNTS] == [
        ("admin@example.test", MembershipRole.ADMIN),
        ("manager@example.test", MembershipRole.MANAGER),
        ("employee@example.test", MembershipRole.EMPLOYEE),
    ]


def test_seed_is_disabled_by_default() -> None:
    with pytest.raises(RuntimeError, match="APP_DEMO_SEED_ENABLED=true"):
        ensure_demo_seed_allowed(Settings(environment="local", demo_seed_enabled=False))


def test_seed_is_forbidden_outside_local_environment() -> None:
    with pytest.raises(RuntimeError, match="APP_ENVIRONMENT=local"):
        ensure_demo_seed_allowed(Settings(environment="production", demo_seed_enabled=True))


def test_seed_is_allowed_only_when_local_and_explicitly_enabled() -> None:
    ensure_demo_seed_allowed(Settings(environment="local", demo_seed_enabled=True))
