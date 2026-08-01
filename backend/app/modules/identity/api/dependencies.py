"""Authentication dependencies shared by current and future product routers."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.errors import ApplicationError
from app.core.config import Settings
from app.modules.identity.application.auth_service import AuthService
from app.modules.identity.domain.auth import (
    AuthenticatedActor,
    AuthenticationRequiredError,
    SessionExpiredError,
)


def get_auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth_service)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_authenticated_actor(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthenticatedActor:
    cookie_value = request.cookies.get(settings.session_cookie_name)
    try:
        return await service.authenticate(cookie_value)
    except AuthenticationRequiredError as exc:
        raise ApplicationError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message_key="common.error.authenticationRequired",
        ) from exc
    except SessionExpiredError as exc:
        raise ApplicationError(
            status_code=401,
            code="SESSION_EXPIRED",
            message_key="common.error.sessionExpired",
        ) from exc


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
ActorDependency = Annotated[AuthenticatedActor, Depends(get_authenticated_actor)]
