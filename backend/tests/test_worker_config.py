import os
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.planning_runs.adapters.ai_runtime import build_planning_job_handlers


def test_worker_organization_ids_parsing() -> None:
    # Test valid JSON list of UUIDs
    os.environ["APP_WORKER_ORGANIZATION_IDS"] = (
        '["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]'
    )
    settings = Settings(environment="test")
    assert settings.worker_organization_ids == [
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
    ]

    # Test invalid UUID rejected
    os.environ["APP_WORKER_ORGANIZATION_IDS"] = '["not-a-uuid"]'
    with pytest.raises(ValidationError):
        Settings(environment="test")

    # Test empty JSON list
    os.environ["APP_WORKER_ORGANIZATION_IDS"] = "[]"
    settings = Settings(environment="test")
    assert settings.worker_organization_ids == []

    # Test empty string from environment (e.g. compose default unset)
    os.environ["APP_WORKER_ORGANIZATION_IDS"] = ""
    settings = Settings(environment="test")
    assert settings.worker_organization_ids == []

    # Clean up
    del os.environ["APP_WORKER_ORGANIZATION_IDS"]


def test_task_7_worker_registers_only_start_resume_and_revalidation_handlers() -> None:
    handlers = build_planning_job_handlers(Settings(environment="test"))

    assert set(handlers) == {"planning.start", "planning.resume", "proposal.revalidate"}
    assert "approval.apply" not in handlers
