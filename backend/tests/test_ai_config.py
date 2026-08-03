"""AI runtime configuration validation tests."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def test_ai_configuration_defaults_to_disabled_without_credentials() -> None:
    settings = Settings(environment="test")

    assert settings.ai_provider == "disabled"
    assert settings.ai_model == ""
    assert settings.openai_api_key is None
    assert settings.langsmith_tracing is False
    assert settings.langsmith_api_key is None
    assert settings.ai_raw_context_retention_days == 30
    assert settings.ai_redacted_trace_retention_days == 90


def test_mock_provider_is_valid_without_external_credentials() -> None:
    settings = Settings(environment="local", ai_provider="mock")

    assert settings.ai_provider == "mock"
    assert settings.openai_api_key is None


@pytest.mark.parametrize(
    ("model", "api_key"),
    [
        ("", SecretStr("provided-key")),
        ("gpt-planning", None),
    ],
)
def test_production_openai_requires_model_and_api_key(
    model: str,
    api_key: SecretStr | None,
) -> None:
    with pytest.raises(ValidationError, match="OpenAI production configuration"):
        Settings(
            environment="production",
            session_secure_cookie=True,
            ai_provider="openai",
            ai_model=model,
            openai_api_key=api_key,
        )


def test_production_openai_accepts_complete_configuration() -> None:
    settings = Settings(
        environment="production",
        session_secure_cookie=True,
        ai_provider="openai",
        ai_model="gpt-planning",
        openai_api_key=SecretStr("provided-key"),
    )

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "provided-key"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ai_raw_context_retention_days", 31),
        ("ai_redacted_trace_retention_days", 91),
        ("ai_raw_context_retention_days", -1),
        ("ai_redacted_trace_retention_days", -1),
    ],
)
def test_ai_retention_cannot_exceed_policy(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


def test_ai_validation_errors_do_not_reveal_secrets() -> None:
    secret = "highly-sensitive-provider-key"

    with pytest.raises(ValidationError) as captured:
        Settings(
            environment="production",
            session_secure_cookie=True,
            ai_provider="openai",
            ai_model="",
            openai_api_key=SecretStr(secret),
        )

    assert secret not in str(captured.value)
