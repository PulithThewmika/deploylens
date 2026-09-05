"""Tests for alert resolution reconciliation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.reconciliation import reconcile_active_alerts, _recovery_counters


def _make_alert_row(alert_id=1, deployment_id=1, service_id=1,
                    service_name="orders", namespace="kubex",
                    prom_components=None):
    row = MagicMock()
    row.id = alert_id
    row.deployment_id = deployment_id
    row.service_id = service_id
    row.service_name = service_name
    row.namespace = namespace
    row.prom_components = prom_components
    return row


def _healthy_aggregated():
    """Baseline and post metrics that produce a healthy score (>= 80)."""
    return {
        "error_rate": 0.005,
        "latency_p99": 110.0,
        "restarts": 0.0,
        "request_rate": 10.0,
    }


def _degraded_aggregated():
    """Post metrics that produce a degraded/failed score (< 80)."""
    return {
        "error_rate": 0.08,
        "latency_p99": 500.0,
        "restarts": 5.0,
        "request_rate": 10.0,
    }


@pytest.fixture(autouse=True)
def clear_counters():
    _recovery_counters.clear()
    yield
    _recovery_counters.clear()


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_no_active_alerts(mock_session):
    result = MagicMock()
    result.fetchall.return_value = []
    mock_session.execute.return_value = result

    resolved = await reconcile_active_alerts(mock_session)

    assert resolved == 0


@pytest.mark.asyncio
async def test_resolve_after_two_healthy_cycles(mock_session):
    """Alert resolves after 2 consecutive cycles where recomputed score >= 80."""
    result = MagicMock()
    result.fetchall.return_value = [_make_alert_row(alert_id=10)]
    mock_session.execute.return_value = result

    with patch("agent.reconciliation._aggregate_metrics", new_callable=AsyncMock) as mock_agg, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock) as mock_resolve:

        mock_agg.return_value = _healthy_aggregated()

        # Cycle 1: healthy but not yet resolved (need 2 consecutive)
        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 0
        assert _recovery_counters[10] == 1
        mock_resolve.assert_not_called()

        # Cycle 2: still healthy → resolved
        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 1
        mock_resolve.assert_awaited_once_with(mock_session, 10, "orders", 1)
        assert 10 not in _recovery_counters


@pytest.mark.asyncio
async def test_resolve_with_realistic_nonzero_metrics(mock_session):
    """Alert resolves when metrics are non-zero but within healthy thresholds.

    This is the regression test for bug #135: previously, any non-zero error
    rate or restart count would pin the alert open forever because the
    reconciliation compared against a hardcoded 0.0 baseline.
    """
    result = MagicMock()
    result.fetchall.return_value = [_make_alert_row(alert_id=15)]
    mock_session.execute.return_value = result

    with patch("agent.reconciliation._aggregate_metrics", new_callable=AsyncMock) as mock_agg, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock) as mock_resolve:

        base = {"error_rate": 0.002, "latency_p99": 100.0, "restarts": 0.0, "request_rate": 12.0}
        post = {"error_rate": 0.003, "latency_p99": 105.0, "restarts": 0.0, "request_rate": 11.0}
        mock_agg.side_effect = [base, post, base, post]

        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 0
        assert _recovery_counters[15] == 1

        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 1
        mock_resolve.assert_awaited_once()


@pytest.mark.asyncio
async def test_flapping_resets_counter(mock_session):
    """If metrics recover then degrade again, counter resets."""
    result = MagicMock()
    result.fetchall.return_value = [_make_alert_row(alert_id=20)]
    mock_session.execute.return_value = result

    with patch("agent.reconciliation._aggregate_metrics", new_callable=AsyncMock) as mock_agg, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock) as mock_resolve:

        # Cycle 1: healthy
        mock_agg.return_value = _healthy_aggregated()
        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 0
        assert _recovery_counters[20] == 1

        # Cycle 2: degraded again
        mock_agg.side_effect = [_healthy_aggregated(), _degraded_aggregated()]
        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 0
        assert _recovery_counters[20] == 0
        mock_resolve.assert_not_called()


@pytest.mark.asyncio
async def test_still_degraded_stays_at_zero(mock_session):
    """Consistently degraded metrics keep counter at 0."""
    result = MagicMock()
    result.fetchall.return_value = [_make_alert_row(alert_id=30)]
    mock_session.execute.return_value = result

    with patch("agent.reconciliation._aggregate_metrics", new_callable=AsyncMock) as mock_agg, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock) as mock_resolve:

        base = _healthy_aggregated()
        post = _degraded_aggregated()
        mock_agg.side_effect = [base, post, base, post]

        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 0
        assert _recovery_counters[30] == 0

        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 0
        assert _recovery_counters[30] == 0
        mock_resolve.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_alerts_independent(mock_session):
    """Each alert has its own recovery counter."""
    result = MagicMock()
    result.fetchall.return_value = [
        _make_alert_row(alert_id=40, service_name="orders"),
        _make_alert_row(alert_id=41, service_name="payments"),
    ]
    mock_session.execute.return_value = result

    async def agg_side_effect(components, namespace, window, timestamp):
        if components == ["orders"]:
            return _healthy_aggregated()
        # payments: baseline healthy, observation degraded → penalty fires
        if window == "30m":
            return _healthy_aggregated()
        return _degraded_aggregated()

    with patch("agent.reconciliation._aggregate_metrics", new_callable=AsyncMock,
               side_effect=agg_side_effect), \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock):

        await reconcile_active_alerts(mock_session)

        assert _recovery_counters[40] == 1  # orders: healthy
        assert _recovery_counters[41] == 0  # payments: still degraded
