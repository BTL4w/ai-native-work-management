"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from app.api.errors import register_error_handlers
from app.core.config import Settings, get_settings

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _resolve_request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID")
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an isolated application instance for runtime or tests."""

    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.name,
        version=resolved_settings.version,
        debug=resolved_settings.debug,
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
    return app


app = create_app()
