"""Tests for Alertmanager client — fire_alert and resolve_alert."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent.alerting import (
    _build_alert_payload,
    fire_alert,
    resolve_alert,
)


SAMPLE_DETAILS = {
    "penalties": {"error_rate": 0.6, "latency_p99": 0.167, "restarts": 0.0},
    "weights": {"error_rate": 45, "latency_p99": 30, "restarts": 25},
    "weighted_sum": 32.0,
    "low_traffic": False,
    "raw_metrics": {
        "error_rate_base": 0.01,
        "error_rate_post": 0.04,
        "latency_p99_base_ms": 100.0,
        "latency_p99_post_ms": 150.0,
        "restarts_base": 0.0,
        "restarts_post": 0.0,
        "request_rate_base": 10.0,
        "request_rate_post": 10.0,
    },
}


class TestBuildAlertPayload:
    def test_degraded_severity_is_warning(self):
        payload = _build_alert_payload("orders", 52, 68, "degraded", SAMPLE_DETAILS)
        assert len(payload) == 1
        assert payload[0]["labels"]["severity"] == "warning"
        assert payload[0]["labels"]["alertname"] == "DeployDegradation"
        assert payload[0]["labels"]["service"] == "orders"
        assert payload[0]["labels"]["deploy_id"] == "52"

    def test_failed_severity_is_critical(self):
        payload = _build_alert_payload("payments", 99, 30, "failed", SAMPLE_DETAILS)
        assert payload[0]["labels"]["severity"] == "critical"

    def test_summary_format(self):
        payload = _build_alert_payload("orders", 52, 68, "degraded", SAMPLE_DETAILS)
        assert "Deploy #52 of orders scored 68/100" in payload[0]["annotations"]["summary"]

    def test_evidence_in_description(self):
        payload = _build_alert_payload("orders", 52, 68, "degraded", SAMPLE_DETAILS)
        desc = payload[0]["annotations"]["description"]
        assert "error_rate" in desc
        assert "latency_p99" in desc


@pytest.fixture
def mock_alertmanager():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.is_closed = False
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    client.post.return_value = resp
    with patch("agent.alerting._client", client):
        yield client


@pytest.fixture
def mock_session():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 42
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_fire_alert_inserts_db_and_posts(mock_session, mock_alertmanager):
    """fire_alert inserts an alerts row and posts to Alertmanager."""
    alert_id = await fire_alert(
        mock_session, "orders", 1, 52, 68, "degraded", SAMPLE_DETAILS
    )
    assert alert_id == 42

    # DB insert called
    assert mock_session.execute.call_count == 1
    call_args = mock_session.execute.call_args
    sql = str(call_args[0][0])
    assert "INSERT INTO alerts" in sql

    # Alertmanager post called
    mock_alertmanager.post.assert_called_once()
    post_args = mock_alertmanager.post.call_args
    assert post_args[0][0] == "/api/v2/alerts"


@pytest.mark.asyncio
async def test_fire_alert_handles_alertmanager_down(mock_session):
    """fire_alert still inserts DB row when Alertmanager is unreachable."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.is_closed = False
    client.post.side_effect = httpx.ConnectError("Connection refused")
    with patch("agent.alerting._client", client):
        alert_id = await fire_alert(
            mock_session, "orders", 1, 52, 68, "degraded", SAMPLE_DETAILS
        )
    assert alert_id == 42  # DB row still created


@pytest.mark.asyncio
async def test_resolve_alert_updates_db_and_posts(mock_session, mock_alertmanager):
    """resolve_alert updates resolved_at and sends endsAt to Alertmanager."""
    await resolve_alert(mock_session, 42, "orders", 52)

    # DB update called
    call_args = mock_session.execute.call_args
    sql = str(call_args[0][0])
    assert "UPDATE alerts" in sql
    assert "resolved_at" in sql

    # Alertmanager resolution posted
    mock_alertmanager.post.assert_called_once()
    post_args = mock_alertmanager.post.call_args
    payload = post_args[1]["json"]
    assert "endsAt" in payload[0]
