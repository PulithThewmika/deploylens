"""Health score computation — doc 05 formula (exact).

Penalties (each clamped 0-1):
  error_rate:   clamp((post - base) / 0.05, 0, 1)
  latency_p99:  clamp((post/base - 1.2) / 1.8, 0, 1)
  restarts:     clamp((post - base) / 3.0, 0, 1)

Weights: error_rate=45, latency_p99=30, restarts=25
Score:   clamp(100 - sum(weight * penalty), 0, 100), rounded to int
Verdict: >=80 healthy, 50-79 degraded, <50 failed

Guard rail: if request volume < 0.1 rps in both windows, skip
error/latency penalties and note in details JSONB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import BASELINE_WINDOW, BASELINE_WINDOW_SECONDS, OBSERVATION_WINDOW, OBSERVATION_WINDOW_SECONDS
from . import promql

logger = logging.getLogger("deploylens.agent.health_score")

WEIGHTS = {
    "error_rate": 45,
    "latency_p99": 30,
    "restarts": 25,
}

LOW_TRAFFIC_THRESHOLD = 0.1  # rps


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min_val and max_val."""
    if value < min_val:
        return min_val
    if value > max_val:
        return max_val
    return value


def penalty(base: float | None, post: float | None, kind: str) -> float:
    """Compute 0-1 penalty for a single metric per doc 05.

    Returns 0.0 if either value is None (no data = no penalty).
    """
    if base is None or post is None:
        return 0.0

    if kind == "error_rate":
        delta = post - base
        return clamp(delta / 0.05, 0.0, 1.0)

    elif kind == "latency_p99":
        if base <= 0:
            return 0.0
        ratio = post / base
        return clamp((ratio - 1.2) / 1.8, 0.0, 1.0)

    elif kind == "restarts":
        delta = post - base
        return clamp(delta / 3.0, 0.0, 1.0)

    else:
        raise ValueError(f"Unknown metric kind: {kind}")


def compute_health_score(metrics: dict) -> tuple[int, str, dict]:
    """Compute health score from baseline and observation metrics.

    Args:
        metrics: dict with keys:
            error_rate_base, error_rate_post,
            latency_p99_base_ms, latency_p99_post_ms,
            restarts_base, restarts_post,
            request_rate_base, request_rate_post

    Returns:
        (score, verdict, details) where:
            score: int 0-100
            verdict: 'healthy' | 'degraded' | 'failed'
            details: dict with per-metric penalties and raw values
    """
    rps_base = metrics.get("request_rate_base")
    rps_post = metrics.get("request_rate_post")
    low_traffic = (
        (rps_base is None or rps_base < LOW_TRAFFIC_THRESHOLD)
        and (rps_post is None or rps_post < LOW_TRAFFIC_THRESHOLD)
    )

    penalties = {}
    skip_reasons = {}

    if low_traffic:
        penalties["error_rate"] = 0.0
        penalties["latency_p99"] = 0.0
        skip_reasons["error_rate"] = "low traffic (<0.1 rps in both windows)"
        skip_reasons["latency_p99"] = "low traffic (<0.1 rps in both windows)"
    else:
        penalties["error_rate"] = penalty(
            metrics.get("error_rate_base"),
            metrics.get("error_rate_post"),
            "error_rate",
        )
        penalties["latency_p99"] = penalty(
            metrics.get("latency_p99_base_ms"),
            metrics.get("latency_p99_post_ms"),
            "latency_p99",
        )

    penalties["restarts"] = penalty(
        metrics.get("restarts_base"),
        metrics.get("restarts_post"),
        "restarts",
    )

    weighted_sum = sum(WEIGHTS[k] * penalties[k] for k in WEIGHTS)
    score = int(round(clamp(100 - weighted_sum, 0, 100)))

    if score >= 80:
        verdict = "healthy"
    elif score >= 50:
        verdict = "degraded"
    else:
        verdict = "failed"

    details = {
        "penalties": {k: round(v, 4) for k, v in penalties.items()},
        "weights": WEIGHTS,
        "weighted_sum": round(weighted_sum, 2),
        "low_traffic": low_traffic,
        "raw_metrics": {
            "error_rate_base": metrics.get("error_rate_base"),
            "error_rate_post": metrics.get("error_rate_post"),
            "latency_p99_base_ms": metrics.get("latency_p99_base_ms"),
            "latency_p99_post_ms": metrics.get("latency_p99_post_ms"),
            "restarts_base": metrics.get("restarts_base"),
            "restarts_post": metrics.get("restarts_post"),
            "request_rate_base": rps_base,
            "request_rate_post": rps_post,
        },
    }
    if skip_reasons:
        details["skip_reasons"] = skip_reasons

    return score, verdict, details


def _max_of(values: list[float | None]) -> float | None:
    """Return the max of non-None values, or None if all are None."""
    valid = [v for v in values if v is not None]
    return max(valid) if valid else None


def _sum_of(values: list[float | None]) -> float | None:
    """Return the sum of non-None values, or None if all are None."""
    valid = [v for v in values if v is not None]
    return sum(valid) if valid else None


async def _query_component(
    component: str, namespace: str, window: str, timestamp: datetime
) -> dict:
    """Query all metrics for a single Prometheus component."""
    return {
        "error_rate": await promql.query_error_rate(component, namespace, window, timestamp),
        "latency_p99": await promql.query_latency_p99(component, namespace, window, timestamp),
        "restarts": await promql.query_restarts(component, namespace, window, timestamp),
        "request_rate": await promql.query_request_rate(component, namespace, window, timestamp),
    }


async def _aggregate_metrics(
    components: list[str], namespace: str, window: str, timestamp: datetime
) -> dict:
    """Query each component and aggregate: max for rates/latency, sum for restarts/rps."""
    results = [
        await _query_component(comp, namespace, window, timestamp)
        for comp in components
    ]
    return {
        "error_rate": _max_of([r["error_rate"] for r in results]),
        "latency_p99": _max_of([r["latency_p99"] for r in results]),
        "restarts": _sum_of([r["restarts"] for r in results]),
        "request_rate": _sum_of([r["request_rate"] for r in results]),
    }


async def assess_deployment(
    session: AsyncSession,
    deployment,
    components: list[str],
    namespace: str,
) -> tuple[int, str, dict] | None:
    """Fetch metrics for both windows, compute health score, and write to DB.

    Args:
        session: async SQLAlchemy session
        deployment: Deployment ORM instance (must have finished_at set)
        components: list of Prometheus service labels to query and aggregate
        namespace: Kubernetes namespace

    Returns:
        (score, verdict, details) tuple, or None if deployment can't be assessed
    """
    if deployment.finished_at is None:
        logger.warning("Deployment %d has no finished_at, skipping", deployment.id)
        return None

    baseline_end = deployment.finished_at
    observation_end = deployment.finished_at + timedelta(seconds=OBSERVATION_WINDOW_SECONDS)

    logger.info(
        "Assessing deployment %d for components %s: baseline window %s before %s, "
        "observation window %s after deployment",
        deployment.id, components, BASELINE_WINDOW,
        baseline_end.isoformat(), OBSERVATION_WINDOW,
    )

    base = await _aggregate_metrics(components, namespace, BASELINE_WINDOW, baseline_end)
    post = await _aggregate_metrics(components, namespace, OBSERVATION_WINDOW, observation_end)

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

    score, verdict, details = compute_health_score(metrics)
    details["components"] = components

    logger.info(
        "Deployment %d scored %d/100 — verdict: %s",
        deployment.id, score, verdict,
    )

    return score, verdict, details
