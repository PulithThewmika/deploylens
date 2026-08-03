"""Tests for GET /api/deployments/{id}/health endpoint."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _mock_health_row(
    deploy_id=1, status="assessed", score=85, verdict="healthy",
    assessed_at=None,
    error_rate_base=0.01, error_rate_post=0.02,
    latency_p99_base_ms=100.0, latency_p99_post_ms=120.0,
    restarts_base=0.0, restarts_post=0.0,
):
    row = MagicMock()
    row.deploy_id = deploy_id
    row.status = status
    row.score = score
    row.verdict = verdict
    row.assessed_at = assessed_at or datetime(2026, 8, 1, 10, 20, 0, tzinfo=timezone.utc)
    row.error_rate_base = error_rate_base
    row.error_rate_post = error_rate_post
    row.latency_p99_base_ms = latency_p99_base_ms
    row.latency_p99_post_ms = latency_p99_post_ms
    row.restarts_base = restarts_base
    row.restarts_post = restarts_post
    return row


@pytest.mark.asyncio
async def test_health_returns_assessed(client, mock_session):
    result = MagicMock()
    result.fetchone.return_value = _mock_health_row()
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments/1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "assessed"
    assert data["score"] == 85
    assert data["verdict"] == "healthy"
    assert len(data["evidence"]) == 3
    assert data["evidence"][0]["metric"] == "error_rate"


@pytest.mark.asyncio
async def test_health_returns_pending(client, mock_session):
    row = MagicMock()
    row.deploy_id = 1
    row.status = "deployed"
    row.score = None
    row.verdict = None
    row.assessed_at = None
    result = MagicMock()
    result.fetchone.return_value = row
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments/1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["score"] is None
    assert data["evidence"] == []


@pytest.mark.asyncio
async def test_health_not_found(client, mock_session):
    result = MagicMock()
    result.fetchone.return_value = None
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments/999/health")

    assert resp.status_code == 404
