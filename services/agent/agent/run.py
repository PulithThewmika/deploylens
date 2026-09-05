"""Detection agent entry point.

Runs a 60-second APScheduler loop that finds unassessed deployments,
computes health scores, and fires alerts on degradation.

The agent is a pure batch processor with no HTTP API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from .config import (
    AGENT_INTERVAL_SECONDS,
    OBSERVATION_WINDOW,
    OBSERVATION_WINDOW_SECONDS,
    BASELINE_WINDOW,
    PROM_URL,
    ALERTMANAGER_URL,
    DATABASE_URL,
    BLAST_RADIUS_INTERVAL_SECONDS,
)
from .db import get_session, dispose_engine, engine
from .health_score import assess_deployment
from .alerting import fire_alert, close_alertmanager_client
from .promql import close_prom_client
from .reconciliation import reconcile_active_alerts
from .blast_radius import run_discovery, get_monitored_namespaces
from .k8s_client import blast_radius_enabled, close_k8s_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kubex.agent")

_shutdown_event = asyncio.Event()


async def _find_unassessed_deployments(session):
    """Find deployments ready for health assessment.

    Criteria: status='deployed', observation window has elapsed,
    no existing health assessment.
    """
    result = await session.execute(
        text("""
            SELECT d.id, d.service_id, d.finished_at, d.commit_sha,
                   s.name AS service_name, s.namespace,
                   s.prom_components
            FROM deployments d
            JOIN services s ON s.id = d.service_id
            WHERE d.status = 'deployed'
              AND d.finished_at IS NOT NULL
              AND d.finished_at + interval '1 second' * :obs_window <= now()
              AND NOT EXISTS (
                  SELECT 1 FROM health_assessments
                  WHERE deployment_id = d.id
              )
            ORDER BY d.finished_at ASC
        """),
        {"obs_window": OBSERVATION_WINDOW_SECONDS},
    )
    return result.fetchall()


async def _process_deployment(session, row) -> None:
    """Score a single deployment: fetch metrics, compute score, write results, alert if needed."""
    deploy_id = row.id
    service_id = row.service_id
    service_name = row.service_name
    namespace = row.namespace
    components = row.prom_components if row.prom_components is not None else [service_name]

    logger.info(
        "Processing deployment %d for %s (commit %s, components=%s)",
        deploy_id, service_name, (row.commit_sha or "unknown")[:7], components,
    )

    # Build a lightweight object with finished_at for assess_deployment
    class _Deploy:
        def __init__(self, r):
            self.id = r.id
            self.finished_at = r.finished_at

    result = await assess_deployment(session, _Deploy(row), components, namespace)
    if result is None:
        logger.warning("Could not assess deployment %d, skipping", deploy_id)
        return

    score, verdict, details = result

    # Insert health_assessments row
    await session.execute(
        text("""
            INSERT INTO health_assessments (
                deployment_id, score, verdict,
                error_rate_base, error_rate_post,
                latency_p99_base_ms, latency_p99_post_ms,
                restarts_base, restarts_post,
                details, assessed_at
            ) VALUES (
                :deployment_id, :score, :verdict,
                :error_rate_base, :error_rate_post,
                :latency_p99_base_ms, :latency_p99_post_ms,
                :restarts_base, :restarts_post,
                :details, now()
            )
        """),
        {
            "deployment_id": deploy_id,
            "score": score,
            "verdict": verdict,
            "error_rate_base": details["raw_metrics"].get("error_rate_base"),
            "error_rate_post": details["raw_metrics"].get("error_rate_post"),
            "latency_p99_base_ms": details["raw_metrics"].get("latency_p99_base_ms"),
            "latency_p99_post_ms": details["raw_metrics"].get("latency_p99_post_ms"),
            "restarts_base": details["raw_metrics"].get("restarts_base"),
            "restarts_post": details["raw_metrics"].get("restarts_post"),
            "details": json.dumps(details),
        },
    )

    # Update deployment status to 'assessed'
    await session.execute(
        text("UPDATE deployments SET status = 'assessed' WHERE id = :id"),
        {"id": deploy_id},
    )

    await session.commit()

    logger.info(
        "Deployment %d assessed: score=%d verdict=%s",
        deploy_id, score, verdict,
    )

    # Fire alert if degraded or failed
    if verdict != "healthy":
        try:
            alert_session = await get_session()
            async with alert_session:
                await fire_alert(
                    alert_session,
                    service_name, service_id, deploy_id,
                    score, verdict, details,
                )
                await alert_session.commit()
        except Exception:
            logger.exception("Failed to fire alert for deployment %d", deploy_id)


async def agent_loop() -> None:
    """Main agent loop — find and process unassessed deployments."""
    try:
        session = await get_session()
        async with session:
            rows = await _find_unassessed_deployments(session)
            count = len(rows)
            logger.info("Agent loop running, found %d unassessed deployment(s)", count)

            for row in rows:
                try:
                    await _process_deployment(session, row)
                except Exception:
                    logger.exception(
                        "Error processing deployment %d, continuing to next", row.id
                    )
                    await session.rollback()

            try:
                resolved = await reconcile_active_alerts(session)
                if resolved:
                    logger.info("Reconciliation resolved %d alert(s)", resolved)
            except Exception:
                logger.exception("Error during alert reconciliation")
                await session.rollback()
    except Exception:
        logger.exception("Agent loop error")


async def blast_radius_loop() -> None:
    """Discover service dependencies and upsert them into service_dependencies."""
    try:
        session = await get_session()
        async with session:
            namespaces = await get_monitored_namespaces(session)
            if not namespaces:
                logger.info("Blast-radius discovery: no monitored namespaces, skipping")
                return
            written = await run_discovery(session, namespaces)
            await session.commit()
            logger.info("Blast-radius discovery complete: %d edge(s) written", written)
    except Exception:
        logger.exception("Blast-radius discovery loop error")


async def verify_connections() -> None:
    """Verify database connectivity on startup."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connection verified: %s", DATABASE_URL.split("@")[-1])
    logger.info("Prometheus endpoint: %s", PROM_URL)
    logger.info("Alertmanager endpoint: %s", ALERTMANAGER_URL)
    logger.info("Baseline window: %s, Observation window: %s", BASELINE_WINDOW, OBSERVATION_WINDOW)


async def shutdown(scheduler: AsyncIOScheduler) -> None:
    """Graceful shutdown."""
    logger.info("Shutting down agent...")
    scheduler.shutdown(wait=False)
    await close_prom_client()
    await close_alertmanager_client()
    await close_k8s_client()
    await dispose_engine()
    logger.info("Agent stopped.")


async def main() -> None:
    logger.info("KubeX Detection Agent starting")
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
    if blast_radius_enabled():
        scheduler.add_job(
            blast_radius_loop,
            "interval",
            seconds=BLAST_RADIUS_INTERVAL_SECONDS,
            id="blast_radius_loop",
            max_instances=1,
            next_run_time=None,
        )
    else:
        logger.info("Blast-radius discovery disabled (K8S_API_SERVER/K8S_TOKEN/K8S_CA_CERT_B64 not set)")
    scheduler.start()

    # Run once immediately on startup to catch up on unassessed deployments
    await agent_loop()
    if blast_radius_enabled():
        await blast_radius_loop()

    # Schedule subsequent runs
    scheduler.reschedule_job("agent_loop", trigger="interval", seconds=AGENT_INTERVAL_SECONDS)
    if blast_radius_enabled():
        scheduler.reschedule_job(
            "blast_radius_loop", trigger="interval", seconds=BLAST_RADIUS_INTERVAL_SECONDS
        )

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
