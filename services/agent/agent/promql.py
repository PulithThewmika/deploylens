"""PromQL query builders and Prometheus HTTP client.

Constructs and executes PromQL queries for each health metric using the
@ modifier for instant evaluation at a specific timestamp. Query set
follows doc 05 exactly.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .config import PROM_URL

logger = logging.getLogger("deploylens.agent.promql")

_client: httpx.AsyncClient | None = None


def get_prom_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=PROM_URL, timeout=10.0)
    return _client


async def close_prom_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def query_prometheus(promql: str, time: datetime) -> float | None:
    """Execute a PromQL instant query at the given timestamp.

    Uses /api/v1/query with the `time` parameter for point-in-time evaluation.
    Returns the scalar float result, or None if no data / error.
    """
    client = get_prom_client()
    ts = time.timestamp()
    try:
        resp = await client.get(
            "/api/v1/query",
            params={"query": promql, "time": ts},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            logger.warning("Prometheus query failed: %s — %s", promql, data)
            return None
        results = data.get("data", {}).get("result", [])
        if not results:
            logger.debug("Empty result for query: %s @ %s", promql, time.isoformat())
            return None
        value_str = results[0]["value"][1]
        value = float(value_str)
        if value != value:  # NaN check
            logger.debug("NaN result for query: %s", promql)
            return None
        return value
    except httpx.HTTPStatusError as e:
        logger.warning("Prometheus HTTP error: %s — %s", e.response.status_code, promql)
        return None
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning("Prometheus unreachable: %s", e)
        return None
    except (KeyError, IndexError, ValueError) as e:
        logger.warning("Failed to parse Prometheus response for %s: %s", promql, e)
        return None


async def query_error_rate(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query HTTP error rate (5xx / total) for a service over a window."""
    promql = (
        f'sum(rate(http_requests_total{{service="{service}",'
        f'namespace="{namespace}",status=~"5.."}}[{window}]))'
        f' / '
        f'sum(rate(http_requests_total{{service="{service}",'
        f'namespace="{namespace}"}}[{window}]))'
    )
    return await query_prometheus(promql, timestamp)


async def query_latency_p99(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query p99 latency in seconds for a service over a window."""
    promql = (
        f'histogram_quantile(0.99,'
        f'sum(rate(http_request_duration_seconds_bucket{{service="{service}",'
        f'namespace="{namespace}"}}[{window}])) by (le))'
    )
    result = await query_prometheus(promql, timestamp)
    if result is not None:
        return result * 1000  # convert to milliseconds
    return None


async def query_restarts(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query container restart count increase over a window."""
    promql = (
        f'sum(increase(kube_pod_container_status_restarts_total'
        f'{{namespace="{namespace}",container="{service}"}}[{window}]))'
    )
    return await query_prometheus(promql, timestamp)


async def query_request_rate(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query request rate (rps) for guard-rail volume check."""
    promql = (
        f'sum(rate(http_requests_total{{service="{service}",'
        f'namespace="{namespace}"}}[{window}]))'
    )
    return await query_prometheus(promql, timestamp)


async def query_cpu(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query CPU usage for a service (stretch — safety score)."""
    promql = (
        f'sum(rate(container_cpu_usage_seconds_total'
        f'{{namespace="{namespace}",container="{service}"}}[{window}]))'
    )
    return await query_prometheus(promql, timestamp)


async def query_memory(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query memory usage in bytes for a service (stretch — safety score)."""
    promql = (
        f'sum(container_memory_working_set_bytes'
        f'{{namespace="{namespace}",container="{service}"}})'
    )
    return await query_prometheus(promql, timestamp)
