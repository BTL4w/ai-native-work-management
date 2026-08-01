"""Task service dependency."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.modules.work.application.task_service import TaskService


def get_task_service(request: Request) -> TaskService:
    return cast(TaskService, request.app.state.task_service)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
