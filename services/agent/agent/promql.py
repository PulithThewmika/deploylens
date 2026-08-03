"""PromQL query builders and Prometheus HTTP client.

Constructs and executes PromQL queries for each health metric using the
@ modifier for instant evaluation at a specific timestamp. Query set
follows doc 05 exactly.

Populated in E6-T2 (#31).
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .config import PROM_URL

logger = logging.getLogger(__name__)

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
    """Execute a PromQL instant query and return the scalar result."""
    # Placeholder — implemented in E6-T2
    raise NotImplementedError("PromQL query execution not yet implemented (E6-T2)")


async def query_error_rate(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query HTTP error rate for a service. Implemented in E6-T2."""
    raise NotImplementedError("query_error_rate not yet implemented (E6-T2)")


async def query_latency_p99(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query p99 latency for a service. Implemented in E6-T2."""
    raise NotImplementedError("query_latency_p99 not yet implemented (E6-T2)")


async def query_restarts(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query container restart count for a service. Implemented in E6-T2."""
    raise NotImplementedError("query_restarts not yet implemented (E6-T2)")


async def query_cpu(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query CPU usage for a service (stretch — safety score). Implemented in E6-T2."""
    raise NotImplementedError("query_cpu not yet implemented (E6-T2)")


async def query_memory(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query memory usage for a service (stretch — safety score). Implemented in E6-T2."""
    raise NotImplementedError("query_memory not yet implemented (E6-T2)")


async def query_request_rate(
    service: str, namespace: str, window: str, timestamp: datetime
) -> float | None:
    """Query request rate (rps) for guard-rail check. Implemented in E6-T2."""
    raise NotImplementedError("query_request_rate not yet implemented (E6-T2)")
