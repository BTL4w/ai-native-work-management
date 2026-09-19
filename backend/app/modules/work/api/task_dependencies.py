"""Task service dependency."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.modules.work.application.task_service import TaskService
from app.modules.work.planning.assignment.application.assignment_service import (
    ExplicitTaskAssignmentService,
)


def get_task_service(request: Request) -> TaskService:
    return cast(TaskService, request.app.state.task_service)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]


def get_explicit_assignment_service(request: Request) -> ExplicitTaskAssignmentService:
    return cast(ExplicitTaskAssignmentService, request.app.state.explicit_assignment_service)


ExplicitAssignmentServiceDependency = Annotated[
    ExplicitTaskAssignmentService, Depends(get_explicit_assignment_service)
]
