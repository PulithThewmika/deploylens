"""Alertmanager client — fires and resolves deployment degradation alerts.

Posts to Alertmanager v2 API and mirrors alert lifecycle to PostgreSQL.

Populated in E8-T1 (#39).
"""

from __future__ import annotations

import logging

import httpx

from .config import ALERTMANAGER_URL

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_alertmanager_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=ALERTMANAGER_URL, timeout=10.0)
    return _client


async def close_alertmanager_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def fire_alert(deployment: dict, health_assessment: dict) -> None:
    """Fire a DeployDegradation alert to Alertmanager and insert alerts row.

    Implemented in E8-T1 (#39).
    """
    raise NotImplementedError("fire_alert not yet implemented (E8-T1)")


async def resolve_alert(alert_id: int) -> None:
    """Send endsAt to Alertmanager and update alerts.resolved_at.

    Implemented in E8-T1 (#39).
    """
    raise NotImplementedError("resolve_alert not yet implemented (E8-T1)")
