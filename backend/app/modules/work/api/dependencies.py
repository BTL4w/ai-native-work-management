"""Project service dependency resolved from the application composition root."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.modules.work.application.project_service import ProjectService


def get_project_service(request: Request) -> ProjectService:
    return cast(ProjectService, request.app.state.project_service)


ProjectServiceDependency = Annotated[ProjectService, Depends(get_project_service)]
