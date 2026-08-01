"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.errors import register_error_handlers
from app.core.config import Settings, get_settings
from app.core.database import create_database_engine, create_session_factory
from app.modules.identity.adapters.runtime import create_auth_runtime
from app.modules.identity.api.routes import router as auth_router
from app.modules.identity.application.auth_service import AuthService
from app.modules.work.adapters.project_repository import SqlAlchemyProjectTransactionFactory
from app.modules.work.api.routes import router as project_router
from app.modules.work.application.project_service import ProjectService

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _resolve_request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID")
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def create_app(
    settings: Settings | None = None,
    auth_service: AuthService | None = None,
    project_service: ProjectService | None = None,
) -> FastAPI:
    """Build an isolated application instance for runtime or tests."""

    resolved_settings = settings or get_settings()
    database_engine: AsyncEngine | None = None
    resolved_auth_service = auth_service
    if resolved_auth_service is None:
        resolved_auth_service, database_engine = create_auth_runtime(resolved_settings)
    resolved_project_service = project_service
    if resolved_project_service is None:
        if database_engine is None:
            database_engine = create_database_engine(resolved_settings)
        resolved_project_service = ProjectService(
            SqlAlchemyProjectTransactionFactory(create_session_factory(database_engine))
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            if database_engine is not None:
                await database_engine.dispose()

    app = FastAPI(
        title=resolved_settings.name,
        version=resolved_settings.version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.auth_service = resolved_auth_service
    app.state.project_service = resolved_project_service
    app.state.database_engine = database_engine
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID", "Idempotency-Key", "If-Match"],
    )

    @app.middleware("http")
    async def request_context(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _resolve_request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    register_error_handlers(app)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(project_router, prefix="/api/v1")
    return app


app = create_app()
