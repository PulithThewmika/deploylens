"""Alert resolution reconciliation.

Checks active (unresolved) alerts each agent cycle. For each, re-queries
current Prometheus metrics and computes whether the service has recovered.
Resolves the alert only after 2 consecutive healthy cycles to avoid flapping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import promql
from .alerting import resolve_alert
from .config import OBSERVATION_WINDOW
from .health_score import penalty

logger = logging.getLogger("deploylens.agent.reconciliation")

_recovery_counters: dict[int, int] = {}


def _is_recovered(error_rate: float | None, latency_base: float | None,
                  latency_post: float | None, restarts: float | None) -> bool:
    """Check if all metric penalties are zero (i.e. service is healthy)."""
    er_penalty = penalty(0.0, error_rate, "error_rate") if error_rate is not None else 0.0
    lat_penalty = penalty(latency_base, latency_post, "latency_p99") if (latency_base is not None and latency_post is not None) else 0.0
    rst_penalty = penalty(0.0, restarts, "restarts") if restarts is not None else 0.0

    return er_penalty == 0.0 and lat_penalty == 0.0 and rst_penalty == 0.0


async def _fetch_active_alerts(session: AsyncSession):
    """Fetch all unresolved alerts with their service info."""
    result = await session.execute(
        text("""
            SELECT a.id, a.deployment_id, a.service_id,
                   s.name AS service_name, s.namespace
            FROM alerts a
            JOIN services s ON s.id = a.service_id
            WHERE a.resolved_at IS NULL
            ORDER BY a.fired_at ASC
        """)
    )
    return result.fetchall()


async def reconcile_active_alerts(session: AsyncSession) -> int:
    """Check active alerts and resolve those with 2 consecutive healthy cycles.

    Returns the number of alerts resolved this cycle.
    """
    rows = await _fetch_active_alerts(session)
    if not rows:
        logger.info("No active alerts to reconcile")
        return 0

    logger.info("Reconciling %d active alert(s)", len(rows))

    now = datetime.now(timezone.utc)
    resolved_count = 0
    seen_alert_ids = set()

    for row in rows:
        alert_id = row.id
        service_name = row.service_name
        namespace = row.namespace
        deploy_id = row.deployment_id
        seen_alert_ids.add(alert_id)

        error_rate = await promql.query_error_rate(
            service_name, namespace, OBSERVATION_WINDOW, now
        )
        latency_post = await promql.query_latency_p99(
            service_name, namespace, OBSERVATION_WINDOW, now
        )
        latency_base = await promql.query_latency_p99(
            service_name, namespace, OBSERVATION_WINDOW, now
        )
        restarts = await promql.query_restarts(
            service_name, namespace, OBSERVATION_WINDOW, now
        )

        recovered = _is_recovered(error_rate, latency_base, latency_post, restarts)

        if recovered:
            _recovery_counters[alert_id] = _recovery_counters.get(alert_id, 0) + 1
            logger.info(
                "Alert #%d (deploy %d, %s): metrics healthy, recovery count %d/2",
                alert_id, deploy_id, service_name, _recovery_counters[alert_id],
            )

            if _recovery_counters[alert_id] >= 2:
                await resolve_alert(session, alert_id, service_name, deploy_id)
                resolved_count += 1
                _recovery_counters.pop(alert_id, None)
                logger.info(
                    "Alert #%d resolved after 2 consecutive healthy cycles",
                    alert_id,
                )
        else:
            if alert_id in _recovery_counters:
                logger.info(
                    "Alert #%d (deploy %d, %s): metrics still degraded, resetting recovery counter",
                    alert_id, deploy_id, service_name,
                )
            _recovery_counters[alert_id] = 0

    for stale_id in list(_recovery_counters.keys()):
        if stale_id not in seen_alert_ids:
            _recovery_counters.pop(stale_id)

    await session.commit()
    return resolved_count
