"""Tests for GET /api/compare endpoint."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _mock_deploy_row(id, service_id=1, service_name="orders",
                     namespace="deploylens", finished_at=None):
    row = MagicMock()
    row.id = id
    row.service_id = service_id
    row.service_name = service_name
    row.namespace = namespace
    row.finished_at = finished_at or datetime(2026, 8, 1, 10, 5, 0, tzinfo=timezone.utc)
    return row


@pytest.mark.asyncio
async def test_compare_returns_metrics(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_deploy_row(id=1),
        _mock_deploy_row(id=2),
    ]
    mock_session.execute.return_value = result

    mock_metrics = {
        "error_rate": 0.02,
        "latency_p99_ms": 150.0,
        "restarts": 0.0,
    }

    with patch("app.promql.fetch_metrics_at", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_metrics

        async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
            resp = await ac.get("/api/compare?a=1&b=2")

    assert resp.status_code == 200
    data = resp.json()
    assert data["deploy_a_id"] == 1
    assert data["deploy_b_id"] == 2
    assert data["service"] == "orders"
    assert len(data["metrics"]) == 3


@pytest.mark.asyncio
async def test_compare_different_services_returns_400(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_deploy_row(id=1, service_id=1),
        _mock_deploy_row(id=2, service_id=2),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/compare?a=1&b=2")

    assert resp.status_code == 400
    assert "same service" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_compare_missing_deployment_returns_404(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_deploy_row(id=1),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/compare?a=1&b=999")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_compare_unfinished_deployment_returns_400(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_deploy_row(id=1),
        _mock_deploy_row(id=2, finished_at=None),
    ]
    # Override finished_at to None
    result.fetchall.return_value[1].finished_at = None
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/compare?a=1&b=2")

    assert resp.status_code == 400
    assert "finished_at" in resp.json()["detail"]
