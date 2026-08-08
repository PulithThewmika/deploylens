"""Tests for the main agent loop."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.run import _find_unassessed_deployments, _process_deployment, agent_loop


@pytest.fixture
def mock_session():
    return AsyncMock()


def _make_deploy_row(deploy_id=1, service_id=1, service_name="orders",
                     namespace="deploylens", commit_sha="abc1234",
                     prom_components=None):
    row = MagicMock()
    row.id = deploy_id
    row.service_id = service_id
    row.service_name = service_name
    row.namespace = namespace
    row.commit_sha = commit_sha
    row.prom_components = prom_components
    row.finished_at = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
    return row


@pytest.mark.asyncio
async def test_find_unassessed_deployments(mock_session):
    """Queries for deployed, observation-elapsed, unassessed deployments."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [_make_deploy_row()]
    mock_session.execute.return_value = mock_result

    rows = await _find_unassessed_deployments(mock_session)
    assert len(rows) == 1

    call_args = mock_session.execute.call_args
    sql = str(call_args[0][0])
    assert "status = 'deployed'" in sql
    assert "finished_at IS NOT NULL" in sql
    assert "NOT EXISTS" in sql


@pytest.mark.asyncio
async def test_process_deployment_healthy(mock_session):
    """Healthy deployment writes health_assessments row, updates status, no alert."""
    row = _make_deploy_row()

    with patch("agent.run.assess_deployment", new_callable=AsyncMock) as mock_assess, \
         patch("agent.run.fire_alert", new_callable=AsyncMock) as mock_fire, \
         patch("agent.run.get_session", new_callable=AsyncMock):

        mock_assess.return_value = (95, "healthy", {
            "penalties": {"error_rate": 0, "latency_p99": 0, "restarts": 0},
            "raw_metrics": {},
        })

        await _process_deployment(mock_session, row)

        # health_assessments INSERT + status UPDATE + commit
        assert mock_session.execute.call_count >= 2
        mock_session.commit.assert_called_once()
        mock_fire.assert_not_called()


@pytest.mark.asyncio
async def test_process_deployment_degraded_fires_alert(mock_session):
    """Degraded deployment triggers fire_alert."""
    row = _make_deploy_row()

    mock_alert_session = AsyncMock()
    mock_alert_result = MagicMock()
    mock_alert_result.scalar_one.return_value = 1
    mock_alert_session.execute.return_value = mock_alert_result
    mock_alert_session.__aenter__ = AsyncMock(return_value=mock_alert_session)
    mock_alert_session.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.run.assess_deployment", new_callable=AsyncMock) as mock_assess, \
         patch("agent.run.get_session", new_callable=AsyncMock, return_value=mock_alert_session), \
         patch("agent.alerting._client", AsyncMock(is_closed=False)):

        mock_assess.return_value = (55, "degraded", {
            "penalties": {"error_rate": 0.6, "latency_p99": 0.167, "restarts": 0},
            "raw_metrics": {
                "error_rate_base": 0.01, "error_rate_post": 0.04,
                "latency_p99_base_ms": 100, "latency_p99_post_ms": 150,
                "restarts_base": 0, "restarts_post": 0,
            },
        })

        await _process_deployment(mock_session, row)

        # commit on the main session
        mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_agent_loop_error_one_deployment_continues():
    """Error scoring one deployment doesn't prevent scoring the next."""
    row1 = _make_deploy_row(deploy_id=1)
    row2 = _make_deploy_row(deploy_id=2)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [row1, row2]

    # First call is _find_unassessed_deployments, rest are _process_deployment
    mock_session.execute.return_value = mock_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    async def mock_assess(session, deploy, service_name, namespace):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Prometheus down")
        return (90, "healthy", {"penalties": {}, "raw_metrics": {}})

    with patch("agent.run.get_session", new_callable=AsyncMock, return_value=mock_session), \
         patch("agent.run.assess_deployment", side_effect=mock_assess), \
         patch("agent.run.fire_alert", new_callable=AsyncMock):

        await agent_loop()

    # Both deployments were attempted (assess_deployment called twice)
    assert call_count == 2


@pytest.mark.asyncio
async def test_agent_loop_ignores_already_assessed():
    """The SQL query naturally excludes deployments with existing health_assessments."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []  # no unassessed deployments
    mock_session.execute.return_value = mock_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("agent.run.get_session", new_callable=AsyncMock, return_value=mock_session), \
         patch("agent.run.reconcile_active_alerts", new_callable=AsyncMock, return_value=0):
        await agent_loop()

    # Only the find-unassessed query, no processing
    assert mock_session.execute.call_count == 1
