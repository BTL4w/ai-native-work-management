"""Background worker entrypoint for processing jobs and outbox events."""

import asyncio
import contextlib
import logging
import signal
import sys
from typing import NoReturn

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.modules.planning_runs.adapters.ai_runtime import build_planning_job_handlers
from app.modules.planning_runs.adapters.transaction import PostgreSQLPlanningRunTransactionFactory
from app.modules.planning_runs.application.job_service import JobService
from app.modules.planning_runs.application.outbox_service import (
    OutboxService,
    UnsupportedOutboxPublisher,
)

logger = logging.getLogger(__name__)


async def _run_worker() -> None:
    settings = get_settings()
    worker_id = settings.worker_id
    organization_ids = settings.worker_organization_ids

    if not organization_ids:
        logger.warning(
            "No worker_organization_ids configured. "
            "Worker is idle and will not process any tenants. "
            "Set APP_WORKER_ORGANIZATION_IDS in your environment."
        )

    # Initialize database
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=10,
        max_overflow=20,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    transaction_factory = PostgreSQLPlanningRunTransactionFactory(session_factory)

    scopes = set(organization_ids)

    # Initialize services
    job_service = JobService(
        transaction_factory=transaction_factory,
        handlers=build_planning_job_handlers(settings),
        organization_scopes=scopes,
        lease_seconds=settings.worker_lease_seconds,
    )
    outbox_service = OutboxService(
        transaction_factory=transaction_factory,
        publisher=UnsupportedOutboxPublisher(),
        organization_scopes=scopes,
        lease_seconds=settings.worker_lease_seconds,
    )

    logger.info("Worker %s started", worker_id)

    poll_interval = settings.worker_poll_interval_seconds
    running = True

    def _handle_shutdown() -> None:
        logger.info("Worker shutting down...")
        nonlocal running
        running = False

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_shutdown)

    while running:
        if not organization_ids:
            await asyncio.sleep(poll_interval)
            continue

        processed_any = False

        for org_id in organization_ids:
            if not running:
                break

            try:
                if await outbox_service.dispatch_once(worker_id, org_id):
                    processed_any = True
            except Exception:
                logger.exception("Error processing outbox for organization %s", org_id)

            if not running:
                break

            try:
                if await job_service.run_once(worker_id, org_id):
                    processed_any = True
            except Exception:
                logger.exception("Error processing jobs for organization %s", org_id)

        if not processed_any and running:
            await asyncio.sleep(poll_interval)

    logger.info("Worker %s stopped", worker_id)


def main() -> NoReturn:
    """Synchronous entrypoint for the worker script."""
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run_worker())
    
    sys.exit(0)


if __name__ == "__main__":
    main()
