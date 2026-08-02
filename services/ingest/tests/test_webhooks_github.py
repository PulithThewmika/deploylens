"""Tests for the GitHub webhook handler."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


def _workflow_run_payload(action="requested", conclusion=None, head_sha="abc1234567890", run_id=12345):
    wr = {
        "id": run_id,
        "head_sha": head_sha,
        "head_branch": "main",
        "actor": {"login": "testuser"},
        "head_commit": {"timestamp": "2026-08-01T10:00:00Z"},
        "run_started_at": "2026-08-01T10:00:00Z",
        "updated_at": "2026-08-01T10:05:00Z",
    }
    if conclusion:
        wr["conclusion"] = conclusion
    return {
        "action": action,
        "workflow_run": wr,
        "repository": {"full_name": "PulithThewmika/deploylens"},
    }


async def _post_github(app, payload_dict, sign_fn):
    payload = json.dumps(payload_dict).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": sign_fn(payload),
                "X-GitHub-Event": "workflow_run",
                "Content-Type": "application/json",
            },
        )


@pytest.mark.asyncio
async def test_requested_creates_building(client, sign_github_payload):
    resp = await _post_github(client, _workflow_run_payload("requested"), sign_github_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["deployment_status"] == "building"


@pytest.mark.asyncio
async def test_completed_success_creates_built(client, sign_github_payload):
    resp = await _post_github(
        client,
        _workflow_run_payload("completed", conclusion="success"),
        sign_github_payload,
    )
    assert resp.status_code == 200
    assert resp.json()["deployment_status"] == "built"


@pytest.mark.asyncio
async def test_completed_failure_creates_build_failed(client, sign_github_payload):
    resp = await _post_github(
        client,
        _workflow_run_payload("completed", conclusion="failure"),
        sign_github_payload,
    )
    assert resp.status_code == 200
    assert resp.json()["deployment_status"] == "build_failed"


@pytest.mark.asyncio
async def test_non_workflow_run_event_ignored(client, sign_github_payload):
    payload = json.dumps({"action": "created"}).encode()

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": sign_github_payload(payload),
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_missing_repo_ignored(client, sign_github_payload):
    payload_dict = _workflow_run_payload("requested")
    payload_dict["repository"]["full_name"] = ""
    resp = await _post_github(client, payload_dict, sign_github_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_unknown_action_ignored(client, sign_github_payload):
    resp = await _post_github(
        client,
        _workflow_run_payload("in_progress"),
        sign_github_payload,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
