"""Lightweight PromQL client for the compare endpoint.

Queries Prometheus for error_rate, latency_p99, and restarts over a
given window at a given timestamp. Mirrors the agent's query patterns.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime

import httpx

logger = logging.getLogger("deploylens.ingest.promql")

PROM_URL = os.environ.get("PROM_URL", "http://localhost:9090")
OBSERVATION_WINDOW = os.environ.get("OBSERVATION_WINDOW", "15m")
BASELINE_WINDOW = os.environ.get("BASELINE_WINDOW", "30m")

_UNSAFE_LABEL_RE = re.compile(r'[\\"\n\r]')


def _sanitize_label(value: str) -> str:
    """Escape characters that break PromQL label matchers."""
    return _UNSAFE_LABEL_RE.sub(lambda m: "\\" + m.group(0), value)

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
    svc, ns = _sanitize_label(service), _sanitize_label(namespace)
    error_rate = await _query(
        f'sum(rate(http_requests_total{{service="{svc}",'
        f'namespace="{ns}",status=~"5.."}}[{window}]))'
        f' / '
        f'sum(rate(http_requests_total{{service="{svc}",'
        f'namespace="{ns}"}}[{window}]))',
        timestamp,
    )

    latency_raw = await _query(
        f'histogram_quantile(0.99,'
        f'sum(rate(http_request_duration_seconds_bucket{{service="{svc}",'
        f'namespace="{ns}"}}[{window}])) by (le))',
        timestamp,
    )
    latency_p99_ms = latency_raw * 1000 if latency_raw is not None else None

    restarts = await _query(
        f'sum(increase(kube_pod_container_status_restarts_total'
        f'{{namespace="{ns}",container="{svc}"}}[{window}]))',
        timestamp,
    )

    return {
        "error_rate": error_rate,
        "latency_p99_ms": latency_p99_ms,
        "restarts": restarts,
    }


async def fetch_cluster_utilization(timestamp: datetime) -> dict[str, float | None]:
    """Cluster-wide CPU/memory utilization percentage, from node_exporter.

    Used by the safety score's "cluster is under load" risk factor — this
    is intentionally cluster-wide (not per-service), unlike fetch_metrics_at.

    Run concurrently, not sequentially: this is called synchronously from
    the GitHub webhook handler (safety score is computed on
    workflow_run.requested, not in the agent's async loop), so a slow or
    unreachable Prometheus must not cost two serial timeouts on top of
    each other and risk exceeding GitHub's webhook delivery timeout.
    """
    cpu_pct, mem_pct = await asyncio.gather(
        _query(
            "100 * (1 - avg(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])))",
            timestamp,
        ),
        _query(
            "100 * (1 - avg(node_memory_MemAvailable_bytes) / avg(node_memory_MemTotal_bytes))",
            timestamp,
        ),
    )
    return {"cpu_pct": cpu_pct, "mem_pct": mem_pct}
