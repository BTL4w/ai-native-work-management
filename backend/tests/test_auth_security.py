"""Unit tests for local-auth security adapters and configuration."""

from uuid import uuid4

import pytest
from pwdlib import PasswordHash
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.identity.adapters.security import (
    Argon2PasswordVerifier,
    OpaqueSessionTokenCodec,
)


def test_password_verifier_accepts_argon2_and_rejects_invalid_inputs() -> None:
    encoded_hash = PasswordHash.recommended().hash("CorrectPassword123!")
    verifier = Argon2PasswordVerifier()

    assert verifier.verify("CorrectPassword123!", encoded_hash) is True
    assert verifier.verify("wrong", encoded_hash) is False
    assert verifier.verify("anything", None) is False
    assert verifier.verify("anything", "not-a-supported-hash") is False


def test_session_codec_round_trip_hashes_only_the_raw_token() -> None:
    organization_id = uuid4()
    codec = OpaqueSessionTokenCodec()

    cookie_value, token_hash = codec.issue(organization_id)
    parsed = codec.parse_and_hash(cookie_value)

    assert parsed == (organization_id, token_hash)
    assert token_hash not in cookie_value
    assert codec.parse_and_hash("") is None
    assert codec.parse_and_hash("not-a-session") is None
    assert codec.parse_and_hash(f"not-a-uuid.{cookie_value}") is None


def test_production_requires_secure_session_cookie() -> None:
    with pytest.raises(ValidationError, match="session_secure_cookie"):
        Settings(environment="production", session_secure_cookie=False)

    settings = Settings(environment="production", session_secure_cookie=True)
    assert settings.session_secure_cookie is True
