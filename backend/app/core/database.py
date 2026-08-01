"""SQLAlchemy engine, session and metadata foundation."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, get_settings

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative metadata for models introduced by an active slice."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_database_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create an async engine without opening a database connection eagerly."""

    resolved_settings = settings or get_settings()
    return create_async_engine(
        resolved_settings.database_url,
        echo=resolved_settings.debug,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create sessions whose transaction lifecycle is owned by application services."""

    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
