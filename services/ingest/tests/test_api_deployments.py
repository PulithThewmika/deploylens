"""Tests for GET /api/deployments and GET /api/deployments/{id} endpoints."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _mock_deploy_list_row(
    id=1, service_id=1, service_name="orders", commit_sha="abc1234",
    branch="main", author="dev", status="deployed", image_tag="abc1234",
    started_at=None, finished_at=None, health_score=90, health_verdict="healthy",
    commit_at=None, build_status=None, build_duration_s=None,
    argocd_revision=None, sync_status=None, assessed_at=None,
):
    row = MagicMock()
    row.id = id
    row.service_id = service_id
    row.service_name = service_name
    row.commit_sha = commit_sha
    row.branch = branch
    row.author = author
    row.status = status
    row.image_tag = image_tag
    row.started_at = started_at or datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    row.finished_at = finished_at or datetime(2026, 8, 1, 10, 5, 0, tzinfo=timezone.utc)
    row.health_score = health_score
    row.health_verdict = health_verdict
    row.commit_at = commit_at
    row.build_status = build_status
    row.build_duration_s = build_duration_s
    row.argocd_revision = argocd_revision
    row.sync_status = sync_status
    row.assessed_at = assessed_at
    return row


def _mock_deploy_detail_row(
    id=1, service_id=1, commit_sha="abc1234", branch="main",
    author="dev", status="assessed", image_tag="abc1234",
    started_at=None, finished_at=None, commit_at=None,
    build_status="completed", build_duration_s=120.0,
    sync_status="completed", workflow_run_id=12345,
    argocd_revision="def5678", created_at=None,
    s_id=1, s_name="orders", s_repo="org/orders",
    s_argocd_app="orders", s_namespace="kubex", s_created_at=None,
    ha_id=1, score=85, verdict="healthy",
    error_rate_base=0.01, error_rate_post=0.02,
    latency_p99_base_ms=100.0, latency_p99_post_ms=120.0,
    restarts_base=0.0, restarts_post=0.0,
    details=None, assessed_at=None,
):
    row = MagicMock()
    row.id = id
    row.service_id = service_id
    row.commit_sha = commit_sha
    row.branch = branch
    row.author = author
    row.status = status
    row.image_tag = image_tag
    row.started_at = started_at or datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    row.finished_at = finished_at or datetime(2026, 8, 1, 10, 5, 0, tzinfo=timezone.utc)
    row.commit_at = commit_at or datetime(2026, 8, 1, 9, 55, 0, tzinfo=timezone.utc)
    row.build_status = build_status
    row.build_duration_s = build_duration_s
    row.sync_status = sync_status
    row.workflow_run_id = workflow_run_id
    row.argocd_revision = argocd_revision
    row.created_at = created_at or datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    row.s_id = s_id
    row.s_name = s_name
    row.s_repo = s_repo
    row.s_argocd_app = s_argocd_app
    row.s_namespace = s_namespace
    row.s_created_at = s_created_at or datetime(2026, 7, 1, tzinfo=timezone.utc)
    row.ha_id = ha_id
    row.score = score
    row.verdict = verdict
    row.error_rate_base = error_rate_base
    row.error_rate_post = error_rate_post
    row.latency_p99_base_ms = latency_p99_base_ms
    row.latency_p99_post_ms = latency_p99_post_ms
    row.restarts_base = restarts_base
    row.restarts_post = restarts_post
    row.details = details
    row.assessed_at = assessed_at or datetime(2026, 8, 1, 10, 20, 0, tzinfo=timezone.utc)
    return row


@pytest.mark.asyncio
async def test_list_deployments_returns_filtered_list(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_deploy_list_row(id=1, status="deployed"),
        _mock_deploy_list_row(id=2, status="assessed"),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments?service=orders&limit=5")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["service_name"] == "orders"
    assert data[0]["health"]["score"] == 90


@pytest.mark.asyncio
async def test_list_deployments_includes_timeline(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_deploy_list_row(
            commit_at=datetime(2026, 8, 1, 9, 55, 0, tzinfo=timezone.utc),
            build_status="completed",
            build_duration_s=90.0,
            argocd_revision="def5678",
            sync_status="completed",
            assessed_at=datetime(2026, 8, 1, 10, 20, 0, tzinfo=timezone.utc),
        ),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments")

    assert resp.status_code == 200
    data = resp.json()
    stages = [stage["stage"] for stage in data[0]["timeline"]]
    assert stages == ["commit", "build", "sync", "deploy", "assess"]


@pytest.mark.asyncio
async def test_list_deployments_without_health(client, mock_session):
    result = MagicMock()
    result.fetchall.return_value = [
        _mock_deploy_list_row(health_score=None, health_verdict=None),
    ]
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["health"] is None


@pytest.mark.asyncio
async def test_deployment_detail_returns_full_response(client, mock_session):
    result = MagicMock()
    result.fetchone.return_value = _mock_deploy_detail_row()
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments/1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert data["service"]["name"] == "orders"
    assert data["health_assessment"]["score"] == 85
    assert len(data["timeline"]) >= 3
    assert len(data["health_evidence"]) >= 2


@pytest.mark.asyncio
async def test_deployment_detail_not_found(client, mock_session):
    result = MagicMock()
    result.fetchone.return_value = None
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments/999")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deployment_detail_no_health_assessment(client, mock_session):
    result = MagicMock()
    result.fetchone.return_value = _mock_deploy_detail_row(
        ha_id=None, score=None, verdict=None,
        error_rate_base=None, error_rate_post=None,
        latency_p99_base_ms=None, latency_p99_post_ms=None,
        restarts_base=None, restarts_post=None,
        assessed_at=None,
    )
    mock_session.execute.return_value = result

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/deployments/1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["health_assessment"] is None
    assert data["health_evidence"] == []
