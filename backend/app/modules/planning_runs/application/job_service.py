"""Service for executing background workflow jobs."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.modules.planning_runs.application.ports import PlanningRunTransaction
from app.modules.planning_runs.domain.models import PlanningRunDomainError, WorkflowJob

logger = logging.getLogger(__name__)


class JobHandler(Protocol):
    """Protocol for strongly typed job handlers."""

    async def __call__(
        self,
        *,
        job: WorkflowJob,
        worker_id: str,
    ) -> None:
        """Execute the job's business logic.

        Args:
            job: The job to execute.
            worker_id: The worker holding the durable lease.
        """
        ...


def compute_backoff_seconds(attempt_count: int) -> int:
    """Compute exponential backoff in seconds capped at 300s (5 mins).

    Args:
        attempt_count: The number of previous attempts (1 for the first failure).

    Returns:
        Seconds to wait before the next attempt.
    """
    if attempt_count <= 0:
        return 0
    exponent = min(attempt_count - 1, 10)
    return min(300, 5 * (2**exponent))


class JobService:
    """Application service for claiming and executing workflow jobs."""

    def __init__(
        self,
        *,
        transaction_factory: Callable[[UUID], PlanningRunTransaction],
        handlers: dict[str, JobHandler],
        organization_scopes: set[UUID],
        lease_seconds: int = 60,
    ) -> None:
        self._transaction_factory = transaction_factory
        self._handlers = handlers
        self._organization_scopes = organization_scopes
        self._lease_seconds = lease_seconds

    @property
    def lease_seconds(self) -> int:
        """The configured lease duration in seconds."""
        return self._lease_seconds

    async def run_once(self, worker_id: str, organization_id: UUID) -> bool:
        """Attempt to claim and execute one pending job.

        Args:
            worker_id: The identity of the worker process.
            organization_id: The tenant scope to operate within.

        Returns:
            True if a job was executed, False if no jobs were pending.

        Raises:
            PlanningRunDomainError: If organization_id is outside allowed scopes.
        """
        if organization_id not in self._organization_scopes:
            raise PlanningRunDomainError(f"Worker organization scope violation: {organization_id}")

        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=self._lease_seconds)

        async with self._transaction_factory(organization_id) as txn:
            job = await txn.repository.claim_job(
                organization_id=organization_id,
                worker_id=worker_id,
                now=now,
                lease_until=lease_until,
            )
            if job is None:
                return False
            await txn.commit()

        handler = self._handlers.get(job.job_type)
        if not handler:
            # We don't have a handler, so we must fail the job immediately
            error_code = "PLANNING_JOB_HANDLER_NOT_REGISTERED"
            logger.error("No handler registered for job type %s", job.job_type)
            async with self._transaction_factory(organization_id) as txn:
                await txn.repository.fail_job(
                    job_id=job.id,
                    worker_id=worker_id,
                    error_message=error_code,
                    next_available_at=now
                    + timedelta(seconds=compute_backoff_seconds(job.attempt_count)),
                )
                await txn.commit()
            return True

        try:
            await handler(job=job, worker_id=worker_id)
        except Exception:
            error_code = "PLANNING_JOB_FAILED"
            logger.warning(
                "Planning job %s failed (attempt %d/%d)",
                job.id,
                job.attempt_count,
                job.max_attempts,
            )
            async with self._transaction_factory(organization_id) as txn:
                backoff = compute_backoff_seconds(job.attempt_count)
                await txn.repository.fail_job(
                    job_id=job.id,
                    worker_id=worker_id,
                    error_message=error_code,
                    next_available_at=now + timedelta(seconds=backoff),
                )
                await txn.commit()
        else:
            async with self._transaction_factory(organization_id) as txn:
                await txn.repository.complete_job(job_id=job.id, worker_id=worker_id)
                await txn.commit()

        return True
