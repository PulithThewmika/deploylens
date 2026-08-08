"""Tests for POST /api/alerts/inbound endpoint."""

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _alertmanager_payload(alerts):
    """Build an Alertmanager webhook_configs payload."""
    return {
        "version": "4",
        "groupKey": "test",
        "status": "resolved" if all(a.get("status") == "resolved" for a in alerts) else "firing",
        "alerts": alerts,
    }


def _resolved_alert(deploy_id="1", service="orders", ends_at="2026-08-01T10:30:00Z"):
    return {
        "status": "resolved",
        "labels": {
            "alertname": "DeployDegradation",
            "service": service,
            "deploy_id": deploy_id,
            "severity": "warning",
        },
        "annotations": {
            "summary": f"Deploy #{deploy_id} of {service} scored 60/100",
            "description": "error_rate: 0.01 → 0.04",
        },
        "endsAt": ends_at,
    }


def _firing_alert(deploy_id="2", service="orders"):
    return {
        "status": "firing",
        "labels": {
            "alertname": "DeployDegradation",
            "service": service,
            "deploy_id": deploy_id,
            "severity": "critical",
        },
        "annotations": {
            "summary": f"Deploy #{deploy_id} of {service} scored 30/100",
        },
        "endsAt": "0001-01-01T00:00:00Z",
    }


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_inbound_rejects_missing_auth(client):
    payload = _alertmanager_payload([_resolved_alert()])

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post("/api/alerts/inbound", json=payload)

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_inbound_rejects_bad_token(client):
    payload = _alertmanager_payload([_resolved_alert()])

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/alerts/inbound", json=payload,
            headers=_auth_headers("wrong-token"),
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_inbound_resolves_alert(client, mock_session, alertmanager_token):
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    payload = _alertmanager_payload([_resolved_alert()])

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/alerts/inbound", json=payload,
            headers=_auth_headers(alertmanager_token),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["resolved"] == 1
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_inbound_duplicate_resolution_is_noop(client, mock_session, alertmanager_token):
    result = MagicMock()
    result.rowcount = 0
    mock_session.execute.return_value = result

    payload = _alertmanager_payload([_resolved_alert()])

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/alerts/inbound", json=payload,
            headers=_auth_headers(alertmanager_token),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["resolved"] == 0


@pytest.mark.asyncio
async def test_inbound_ignores_firing_alerts(client, mock_session, alertmanager_token):
    payload = _alertmanager_payload([_firing_alert()])

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/alerts/inbound", json=payload,
            headers=_auth_headers(alertmanager_token),
        )

    assert resp.status_code == 200
    assert resp.json()["resolved"] == 0
    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_inbound_mixed_alerts(client, mock_session, alertmanager_token):
    result = MagicMock()
    result.rowcount = 1
    mock_session.execute.return_value = result

    payload = _alertmanager_payload([
        _firing_alert(deploy_id="3"),
        _resolved_alert(deploy_id="1"),
        _resolved_alert(deploy_id="2"),
    ])

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/alerts/inbound", json=payload,
            headers=_auth_headers(alertmanager_token),
        )

    assert resp.status_code == 200
    assert resp.json()["resolved"] == 2


@pytest.mark.asyncio
async def test_inbound_missing_labels_skipped(client, mock_session, alertmanager_token):
    alert = {
        "status": "resolved",
        "labels": {"alertname": "DeployDegradation"},
        "endsAt": "2026-08-01T10:30:00Z",
    }
    payload = _alertmanager_payload([alert])

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/alerts/inbound", json=payload,
            headers=_auth_headers(alertmanager_token),
        )

    assert resp.status_code == 200
    assert resp.json()["resolved"] == 0
    mock_session.execute.assert_not_awaited()
