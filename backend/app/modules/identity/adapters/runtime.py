"""Composition helpers for the local authentication adapters."""

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.database import create_database_engine, create_session_factory
from app.modules.identity.adapters.auth_repository import SqlAlchemyAuthTransactionFactory
from app.modules.identity.adapters.security import (
    Argon2PasswordVerifier,
    OpaqueSessionTokenCodec,
)
from app.modules.identity.application.auth_service import AuthService


def create_auth_runtime(settings: Settings) -> tuple[AuthService, AsyncEngine]:
    """Compose the auth use cases with PostgreSQL and local security adapters."""

    engine = create_database_engine(settings)
    transaction_factory = SqlAlchemyAuthTransactionFactory(create_session_factory(engine))
    service = AuthService(
        transaction_factory=transaction_factory,
        password_verifier=Argon2PasswordVerifier(),
        token_codec=OpaqueSessionTokenCodec(),
        organization_slug=settings.local_auth_organization_slug,
        session_ttl_seconds=settings.session_ttl_seconds,
    )
    return service, engine
