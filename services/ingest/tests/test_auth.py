"""Tests for webhook authentication — HMAC (GitHub) and bearer token (ArgoCD)."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_github_valid_signature(client, sign_github_payload):
    payload = json.dumps({
        "action": "requested",
        "workflow_run": {"id": 1, "head_sha": "abc1234", "head_branch": "main", "actor": {"login": "user"}},
        "repository": {"full_name": "org/repo"},
    }).encode()

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": sign_github_payload(payload),
                "X-GitHub-Event": "workflow_run",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_github_missing_signature(client):
    payload = json.dumps({"action": "requested"}).encode()

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/webhooks/github",
            content=payload,
            headers={"X-GitHub-Event": "workflow_run", "Content-Type": "application/json"},
        )
    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_github_bad_signature(client):
    payload = json.dumps({"action": "requested"}).encode()

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=badbadbadbad",
                "X-GitHub-Event": "workflow_run",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_argocd_valid_token(client, argocd_token):
    payload = json.dumps({
        "type": "on-sync-succeeded",
        "app": {"metadata": {"name": "sample-app"}, "status": {"sync": {"revision": "abc1234"}, "operationState": {}}},
    })

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/webhooks/argocd",
            content=payload,
            headers={
                "Authorization": f"Bearer {argocd_token}",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Bug #115: requires fix/115-argocd-auth-401 to be merged", strict=False)
async def test_argocd_missing_auth_returns_401(client):
    """Regression test for bug #115 — was returning 422."""
    payload = json.dumps({"type": "on-sync-succeeded", "app": {"metadata": {"name": "test"}}})

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/webhooks/argocd",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_argocd_bad_token_returns_401(client):
    payload = json.dumps({"type": "on-sync-succeeded", "app": {"metadata": {"name": "test"}}})

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/webhooks/argocd",
            content=payload,
            headers={
                "Authorization": "Bearer wrong-token",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 401
