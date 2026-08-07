"""Tests for alert resolution reconciliation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.reconciliation import reconcile_active_alerts, _recovery_counters


def _make_alert_row(alert_id=1, deployment_id=1, service_id=1,
                    service_name="orders", namespace="deploylens"):
    row = MagicMock()
    row.id = alert_id
    row.deployment_id = deployment_id
    row.service_id = service_id
    row.service_name = service_name
    row.namespace = namespace
    return row


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
    """Alert resolves after 2 consecutive cycles where metrics are healthy."""
    result = MagicMock()
    result.fetchall.return_value = [_make_alert_row(alert_id=10)]
    mock_session.execute.return_value = result

    with patch("agent.reconciliation.promql") as mock_promql, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock) as mock_resolve:

        mock_promql.query_error_rate = AsyncMock(return_value=0.0)
        mock_promql.query_latency_p99 = AsyncMock(return_value=100.0)
        mock_promql.query_restarts = AsyncMock(return_value=0.0)

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
async def test_flapping_resets_counter(mock_session):
    """If metrics recover then degrade again, counter resets."""
    result = MagicMock()
    result.fetchall.return_value = [_make_alert_row(alert_id=20)]
    mock_session.execute.return_value = result

    with patch("agent.reconciliation.promql") as mock_promql, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock) as mock_resolve:

        # Cycle 1: healthy
        mock_promql.query_error_rate = AsyncMock(return_value=0.0)
        mock_promql.query_latency_p99 = AsyncMock(return_value=100.0)
        mock_promql.query_restarts = AsyncMock(return_value=0.0)

        resolved = await reconcile_active_alerts(mock_session)
        assert resolved == 0
        assert _recovery_counters[20] == 1

        # Cycle 2: degraded again (high error rate)
        mock_promql.query_error_rate = AsyncMock(return_value=0.08)

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

    with patch("agent.reconciliation.promql") as mock_promql, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock) as mock_resolve:

        mock_promql.query_error_rate = AsyncMock(return_value=0.1)
        mock_promql.query_latency_p99 = AsyncMock(return_value=500.0)
        mock_promql.query_restarts = AsyncMock(return_value=5.0)

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

    call_count = 0

    async def error_rate_side_effect(service, namespace, window, time):
        nonlocal call_count
        call_count += 1
        if service == "orders":
            return 0.0
        return 0.1

    with patch("agent.reconciliation.promql") as mock_promql, \
         patch("agent.reconciliation.resolve_alert", new_callable=AsyncMock):

        mock_promql.query_error_rate = AsyncMock(side_effect=error_rate_side_effect)
        mock_promql.query_latency_p99 = AsyncMock(return_value=100.0)
        mock_promql.query_restarts = AsyncMock(return_value=0.0)

        await reconcile_active_alerts(mock_session)

        assert _recovery_counters[40] == 1  # orders: healthy
        assert _recovery_counters[41] == 0  # payments: still degraded
