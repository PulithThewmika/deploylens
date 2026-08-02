"""Tests for the ArgoCD webhook handler."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


def _argocd_payload(event_type="on-sync-succeeded", app_name="sample-app", revision="abc1234567890"):
    return {
        "type": event_type,
        "app": {
            "metadata": {"name": app_name},
            "status": {
                "sync": {"status": "Synced", "revision": revision},
                "health": {"status": "Healthy"},
                "operationState": {
                    "phase": "Succeeded",
                    "message": "",
                    "syncResult": {"revision": revision},
                },
            },
        },
    }


async def _post_argocd(app, payload_dict, token):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(
            "/webhooks/argocd",
            content=json.dumps(payload_dict),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )


@pytest.mark.asyncio
async def test_sync_succeeded_returns_deployed(client, argocd_token):
    resp = await _post_argocd(client, _argocd_payload("on-sync-succeeded"), argocd_token)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["deployment_status"] == "deployed"


@pytest.mark.asyncio
async def test_sync_running_returns_syncing(client, argocd_token):
    resp = await _post_argocd(client, _argocd_payload("on-sync-running"), argocd_token)
    assert resp.status_code == 200
    assert resp.json()["deployment_status"] == "syncing"


@pytest.mark.asyncio
async def test_sync_failed_returns_sync_failed(client, argocd_token):
    resp = await _post_argocd(client, _argocd_payload("on-sync-failed"), argocd_token)
    assert resp.status_code == 200
    assert resp.json()["deployment_status"] == "sync_failed"


@pytest.mark.asyncio
async def test_missing_app_name_ignored(client, argocd_token):
    resp = await _post_argocd(client, _argocd_payload(app_name=""), argocd_token)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_missing_revision_ignored(client, argocd_token):
    payload = _argocd_payload(revision="")
    payload["app"]["status"]["operationState"]["syncResult"]["revision"] = ""
    resp = await _post_argocd(client, payload, argocd_token)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_unknown_event_type_ignored(client, argocd_token):
    resp = await _post_argocd(client, _argocd_payload("on-health-degraded"), argocd_token)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_orphan_created_when_no_matching_deployment(client, argocd_token):
    resp = await _post_argocd(client, _argocd_payload("on-sync-succeeded"), argocd_token)
    assert resp.status_code == 200
    assert resp.json()["correlation"] == "orphan"
