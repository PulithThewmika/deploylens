"""Lightweight PromQL client for the compare endpoint.

Queries Prometheus for error_rate, latency_p99, and restarts over a
given window at a given timestamp. Mirrors the agent's query patterns.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger("deploylens.ingest.promql")

PROM_URL = os.environ.get("PROM_URL", "http://localhost:9090")
OBSERVATION_WINDOW = os.environ.get("OBSERVATION_WINDOW", "15m")
BASELINE_WINDOW = os.environ.get("BASELINE_WINDOW", "30m")

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=PROM_URL, timeout=10.0)
    return _client


async def _query(promql: str, time: datetime) -> float | None:
    client = _get_client()
    try:
        resp = await client.get(
            "/api/v1/query",
            params={"query": promql, "time": time.timestamp()},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            return None
        results = data.get("data", {}).get("result", [])
        if not results:
            return None
        value = float(results[0]["value"][1])
        if value != value:
            return None
        return value
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None


async def fetch_metrics_at(
    service: str, namespace: str, window: str, timestamp: datetime,
) -> dict[str, float | None]:
    error_rate = await _query(
        f'sum(rate(http_requests_total{{service="{service}",'
        f'namespace="{namespace}",status=~"5.."}}[{window}]))'
        f' / '
        f'sum(rate(http_requests_total{{service="{service}",'
        f'namespace="{namespace}"}}[{window}]))',
        timestamp,
    )

    latency_raw = await _query(
        f'histogram_quantile(0.99,'
        f'sum(rate(http_request_duration_seconds_bucket{{service="{service}",'
        f'namespace="{namespace}"}}[{window}])) by (le))',
        timestamp,
    )
    latency_p99_ms = latency_raw * 1000 if latency_raw is not None else None

    restarts = await _query(
        f'sum(increase(kube_pod_container_status_restarts_total'
        f'{{namespace="{namespace}",container="{service}"}}[{window}]))',
        timestamp,
    )

    return {
        "error_rate": error_rate,
        "latency_p99_ms": latency_p99_ms,
        "restarts": restarts,
    }
