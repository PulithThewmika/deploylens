"""Tests for GET /api/alerts endpoint."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _mock_alert_row(
    id=1, deployment_id=10, service_id=1, severity="warning",
    title="DeployDegradation", description="Score 65/100",
    fired_at=None, resolved_at=None, alertmanager_id=None,
):
    row = MagicMock()
    row.id = id
    row.deployment_id = deployment_id
    row.service_id = service_id
    row.severity = severity
    row.title = title
    row.description = description
    row.fired_at = fired_at or datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    row.resolved_at = resolved_at
    row.alertmanager_id = alertmanager_id
    return row


@pytest.mark.asyncio
async def test_alerts_returns_list(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_alert_row(id=1, severity="warning"),
        _mock_alert_row(id=2, severity="critical"),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/alerts")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["severity"] == "warning"
    assert data[1]["severity"] == "critical"


@pytest.mark.asyncio
async def test_alerts_active_filter(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [_mock_alert_row()]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/alerts?active=true")

    assert resp.status_code == 200
    sql = str(mock_session.execute.call_args[0][0])
    assert "resolved_at IS NULL" in sql


@pytest.mark.asyncio
async def test_alerts_service_filter(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = []
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/alerts?service=orders")

    assert resp.status_code == 200
    sql = str(mock_session.execute.call_args[0][0])
    assert "s.name = :service" in sql


@pytest.mark.asyncio
async def test_alerts_empty(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = []
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/alerts")

    assert resp.status_code == 200
    assert resp.json() == []
