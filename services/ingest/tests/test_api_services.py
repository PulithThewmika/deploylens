"""Tests for GET /api/services endpoint."""

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _mock_row(
    id=1, name="orders", namespace="kubex", repo="org/orders",
    argocd_app="orders", latest_commit_sha="abc1234",
    latest_author="dev", latest_status="deployed",
    latest_finished_at=None, health_score=95,
    health_verdict="healthy", active_alert_count=0,
):
    row = MagicMock()
    row.id = id
    row.name = name
    row.namespace = namespace
    row.repo = repo
    row.argocd_app = argocd_app
    row.latest_commit_sha = latest_commit_sha
    row.latest_author = latest_author
    row.latest_status = latest_status
    row.latest_finished_at = latest_finished_at
    row.health_score = health_score
    row.health_verdict = health_verdict
    row.active_alert_count = active_alert_count
    return row


@pytest.mark.asyncio
async def test_services_returns_correct_structure(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_row(id=1, name="frontend"),
        _mock_row(id=2, name="orders"),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/services")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["name"] == "frontend"
    assert data[0]["health"]["score"] == 95
    assert data[0]["health"]["verdict"] == "healthy"
    assert data[0]["active_alert_count"] == 0


@pytest.mark.asyncio
async def test_services_with_no_deploy_or_health(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_row(
            id=3, name="payments",
            latest_status=None, latest_commit_sha=None,
            health_score=None, health_verdict=None,
        ),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/services")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["latest_deploy"] is None
    assert data[0]["health"] is None


@pytest.mark.asyncio
async def test_services_empty(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = []
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/services")

    assert resp.status_code == 200
    assert resp.json() == []
