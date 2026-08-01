"""Local Argon2 password and opaque session-token adapters."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


class Argon2PasswordVerifier:
    """Verify real or dummy hashes to reduce email-enumeration timing differences."""

    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()
        self._dummy_hash = self._password_hash.hash(secrets.token_urlsafe(24))

    def verify(self, password: str, encoded_hash: str | None) -> bool:
        target_hash = encoded_hash or self._dummy_hash
        try:
            verified = self._password_hash.verify(password, target_hash)
        except UnknownHashError:
            return False
        return encoded_hash is not None and verified


class OpaqueSessionTokenCodec:
    """Keep raw session tokens in cookies and deterministic hashes in PostgreSQL."""

    _TOKEN_BYTES = 32
    _MAX_COOKIE_LENGTH = 256

    def issue(self, organization_id: UUID) -> tuple[str, str]:
        raw_token = secrets.token_urlsafe(self._TOKEN_BYTES)
        return f"{organization_id}.{raw_token}", self._hash(raw_token)

    def parse_and_hash(self, cookie_value: str) -> tuple[UUID, str] | None:
        if not cookie_value or len(cookie_value) > self._MAX_COOKIE_LENGTH:
            return None
        organization_text, separator, raw_token = cookie_value.partition(".")
        if not separator or not raw_token:
            return None
        try:
            organization_id = UUID(organization_text)
        except ValueError:
            return None
        return organization_id, self._hash(raw_token)

    @staticmethod
    def _hash(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
