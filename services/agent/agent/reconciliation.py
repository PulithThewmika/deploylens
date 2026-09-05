"""Alert resolution reconciliation.

Checks active (unresolved) alerts each agent cycle. For each, re-queries
current Prometheus metrics with proper baseline/observation windows and
computes a health score. Resolves the alert only after 2 consecutive
healthy cycles (score >= 80) to avoid flapping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .alerting import resolve_alert
from .config import BASELINE_WINDOW, BASELINE_WINDOW_SECONDS, OBSERVATION_WINDOW, OBSERVATION_WINDOW_SECONDS
from .health_score import compute_health_score, _aggregate_metrics

logger = logging.getLogger("kubex.agent.reconciliation")

HEALTHY_THRESHOLD = 80

_recovery_counters: dict[int, int] = {}


async def _fetch_active_alerts(session: AsyncSession):
    """Fetch all unresolved alerts with their service info."""
    result = await session.execute(
        text("""
            SELECT a.id, a.deployment_id, a.service_id,
                   s.name AS service_name, s.namespace,
                   s.prom_components
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
    baseline_end = now - timedelta(seconds=OBSERVATION_WINDOW_SECONDS)
    resolved_count = 0
    seen_alert_ids = set()

    for row in rows:
        alert_id = row.id
        service_name = row.service_name
        namespace = row.namespace
        deploy_id = row.deployment_id
        components = row.prom_components if row.prom_components is not None else [service_name]
        seen_alert_ids.add(alert_id)

        base = await _aggregate_metrics(components, namespace, BASELINE_WINDOW, baseline_end)
        post = await _aggregate_metrics(components, namespace, OBSERVATION_WINDOW, now)

        metrics = {
            "error_rate_base": base["error_rate"],
            "error_rate_post": post["error_rate"],
            "latency_p99_base_ms": base["latency_p99"],
            "latency_p99_post_ms": post["latency_p99"],
            "restarts_base": base["restarts"],
            "restarts_post": post["restarts"],
            "request_rate_base": base["request_rate"],
            "request_rate_post": post["request_rate"],
        }

        score, verdict, _ = compute_health_score(metrics)
        recovered = score >= HEALTHY_THRESHOLD

        if recovered:
            _recovery_counters[alert_id] = _recovery_counters.get(alert_id, 0) + 1
            logger.info(
                "Alert #%d (deploy %d, %s): score %d/100 — healthy, recovery count %d/2",
                alert_id, deploy_id, service_name, score, _recovery_counters[alert_id],
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
                    "Alert #%d (deploy %d, %s): score %d/100 — still degraded, resetting recovery counter",
                    alert_id, deploy_id, service_name, score,
                )
            _recovery_counters[alert_id] = 0

    for stale_id in list(_recovery_counters.keys()):
        if stale_id not in seen_alert_ids:
            _recovery_counters.pop(stale_id)

    await session.commit()
    return resolved_count
