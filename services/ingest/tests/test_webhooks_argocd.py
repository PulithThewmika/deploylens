"""Tests for the ArgoCD webhook handler."""

import json
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql


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
    data = resp.json()
    assert data["deployment_status"] == "syncing"
    assert data["correlation"] == "orphan"


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


@pytest.mark.asyncio
async def test_sync_succeeded_correlates_by_commit_sha_merges_single_row(client, mock_session, argocd_token):
    """A revision that matches an existing deployment's commit_sha must merge into
    that row instead of creating a second (orphan) one."""
    existing_deployment = MagicMock(id=100, status="building")
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = None  # pipeline_events insert
        elif call_count == 2:
            result.scalar_one_or_none.return_value = MagicMock(id=1)  # resolve_service
        else:
            result.scalar_one_or_none.return_value = existing_deployment  # commit_sha match
        return result

    mock_session.execute = mock_execute

    resp = await _post_argocd(client, _argocd_payload("on-sync-succeeded", revision="abc1234567890"), argocd_token)
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlation"] == "commit_sha"
    assert data["deployment_status"] == "deployed"
    assert existing_deployment.status == "deployed"
    assert call_count == 3  # no pg_insert executed — merged into the existing row


@pytest.mark.asyncio
async def test_sync_succeeded_correlates_by_image_tag_fallback_merges_single_row(client, mock_session, argocd_token):
    """When the ArgoCD sync revision (post image-tag-bump commit) doesn't match the
    original commit_sha, the image_tag fallback must still merge into the same row."""
    existing_deployment = MagicMock(id=200, status="building")
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = None  # pipeline_events insert
        elif call_count == 2:
            result.scalar_one_or_none.return_value = MagicMock(id=1)  # resolve_service
        elif call_count == 3:
            result.scalar_one_or_none.return_value = None  # commit_sha miss
        else:
            result.scalar_one_or_none.return_value = existing_deployment  # image_tag match
        return result

    mock_session.execute = mock_execute

    resp = await _post_argocd(client, _argocd_payload("on-sync-succeeded", revision="bump999"), argocd_token)
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlation"] == "image_tag"
    assert data["deployment_status"] == "deployed"
    assert existing_deployment.status == "deployed"
    assert call_count == 4  # no pg_insert executed — merged into the existing row


@pytest.mark.asyncio
async def test_duplicate_argocd_event_delivery_is_idempotent(client, mock_session, argocd_token):
    """Redelivered ArgoCD notifications must upsert via ON CONFLICT, never a bare
    insert (see partial unique index on deployments(argocd_revision, service_id))."""
    executed_statements = []
    original_execute = mock_session.execute

    async def capture_execute(stmt):
        executed_statements.append(stmt)
        return await original_execute(stmt)

    mock_session.execute = capture_execute

    payload = _argocd_payload("on-sync-succeeded", revision="dup1234567890")
    resp1 = await _post_argocd(client, payload, argocd_token)
    resp2 = await _post_argocd(client, payload, argocd_token)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()

    deployment_stmts = [s for s in executed_statements if getattr(getattr(s, "table", None), "name", None) == "deployments"]
    assert len(deployment_stmts) == 2
    for stmt in deployment_stmts:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT" in compiled
        assert "argocd_revision" in compiled
