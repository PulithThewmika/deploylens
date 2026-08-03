"""Detection agent entry point.

Runs a 60-second APScheduler loop that finds unassessed deployments,
computes health scores, and fires alerts on degradation.

The agent is a pure batch processor with no HTTP API.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from .config import (
    AGENT_INTERVAL_SECONDS,
    OBSERVATION_WINDOW_SECONDS,
    PROM_URL,
    ALERTMANAGER_URL,
    DATABASE_URL,
)
from .db import get_session, dispose_engine, engine
from .promql import close_prom_client
from .alerting import close_alertmanager_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("deploylens.agent")

_shutdown_event = asyncio.Event()


async def agent_loop() -> None:
    """Main agent loop — find and process unassessed deployments."""
    try:
        session = await get_session()
        async with session:
            result = await session.execute(
                text("""
                    SELECT COUNT(*) FROM deployments
                    WHERE status = 'deployed'
                      AND finished_at IS NOT NULL
                      AND finished_at + interval '1 second' * :obs_window <= now()
                      AND NOT EXISTS (
                          SELECT 1 FROM health_assessments
                          WHERE deployment_id = deployments.id
                      )
                """),
                {"obs_window": OBSERVATION_WINDOW_SECONDS},
            )
            count = result.scalar_one()
            logger.info("Agent loop running, found %d unassessed deployments", count)
    except Exception:
        logger.exception("Agent loop error")


async def verify_connections() -> None:
    """Verify database connectivity on startup."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connection verified: %s", DATABASE_URL.split("@")[-1])
    logger.info("Prometheus endpoint: %s", PROM_URL)
    logger.info("Alertmanager endpoint: %s", ALERTMANAGER_URL)


async def shutdown(scheduler: AsyncIOScheduler) -> None:
    """Graceful shutdown."""
    logger.info("Shutting down agent...")
    scheduler.shutdown(wait=False)
    await close_prom_client()
    await close_alertmanager_client()
    await dispose_engine()
    logger.info("Agent stopped.")


async def main() -> None:
    logger.info("DeployLens Detection Agent starting")
    logger.info("Loop interval: %ds", AGENT_INTERVAL_SECONDS)

    await verify_connections()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        agent_loop,
        "interval",
        seconds=AGENT_INTERVAL_SECONDS,
        id="agent_loop",
        max_instances=1,
        next_run_time=None,
    )
    scheduler.start()

    # Run once immediately on startup to catch up on unassessed deployments
    await agent_loop()

    # Schedule subsequent runs
    scheduler.reschedule_job("agent_loop", trigger="interval", seconds=AGENT_INTERVAL_SECONDS)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: _shutdown_event.set())
        except NotImplementedError:
            signal.signal(sig, lambda s, f: _shutdown_event.set())

    logger.info("Agent running — waiting for shutdown signal")
    await _shutdown_event.wait()
    await shutdown(scheduler)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
