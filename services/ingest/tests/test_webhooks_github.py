"""Tests for the GitHub webhook handler."""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql


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
async def test_completed_does_not_regress_status_past_built(client, mock_session, sign_github_payload):
    """Regression test: live E2E testing showed ArgoCD can sync (and fire its
    on-sync-succeeded webhook) before a slower-arriving 'completed' GitHub
    event lands, if ArgoCD's poll happens to catch the manifest change while
    the build is still running. A late 'completed' event must not regress
    the deployment's status/finished_at back from 'deployed' to 'built' —
    the UPDATE must guard status/finished_at with the same CASE the
    'requested' branch already uses, only applying while still
    pending/building."""
    executed_statements = []
    original_execute = mock_session.execute

    async def capture_execute(stmt):
        executed_statements.append(stmt)
        return await original_execute(stmt)

    mock_session.execute = capture_execute

    resp = await _post_github(
        client, _workflow_run_payload("completed", conclusion="success"), sign_github_payload,
    )
    assert resp.status_code == 200

    deployment_stmts = [
        s for s in executed_statements if getattr(getattr(s, "table", None), "name", None) == "deployments"
    ]
    assert len(deployment_stmts) == 1
    compiled = str(deployment_stmts[0].compile(dialect=postgresql.dialect()))
    # Both status and finished_at must be guarded by the same "only while
    # still pending/building" CASE the "requested" branch uses — a bare
    # unconditional assignment here is exactly what let ArgoCD's
    # already-"deployed" status get regressed back to "built".
    assert "status = CASE WHEN (deployments.status IN" in compiled
    assert "finished_at = CASE WHEN (deployments.status IN" in compiled


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


@pytest.mark.asyncio
async def test_duplicate_workflow_run_delivery_is_idempotent(client, mock_session, sign_github_payload):
    """Redelivered webhooks must upsert via ON CONFLICT, never a bare insert (see
    partial unique index on deployments(workflow_run_id))."""
    executed_statements = []
    original_execute = mock_session.execute

    async def capture_execute(stmt):
        executed_statements.append(stmt)
        return await original_execute(stmt)

    mock_session.execute = capture_execute

    payload = _workflow_run_payload("requested", run_id=99999)
    resp1 = await _post_github(client, payload, sign_github_payload)
    resp2 = await _post_github(client, payload, sign_github_payload)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()
    assert resp1.json()["status"] == "ok"
    assert resp1.json()["deployment_status"] == "building"

    deployment_stmts = [s for s in executed_statements if getattr(getattr(s, "table", None), "name", None) == "deployments"]
    assert len(deployment_stmts) == 2
    for stmt in deployment_stmts:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT" in compiled
        assert "workflow_run_id" in compiled
