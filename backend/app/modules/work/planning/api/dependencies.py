"""Manual planning service dependency."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.modules.work.planning.application.manual_service import ManualPlanningService


def get_manual_planning_service(request: Request) -> ManualPlanningService:
    return cast(ManualPlanningService, request.app.state.manual_planning_service)


ManualPlanningServiceDependency = Annotated[
    ManualPlanningService, Depends(get_manual_planning_service)
]
