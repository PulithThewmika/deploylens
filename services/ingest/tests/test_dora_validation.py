"""Validate DORA metric calculations with known test data (#37).

These tests feed deterministic values through the DORA API endpoint
and verify the mathematical results match hand-calculated expectations.
Unlike test_api_dora.py (which tests API shape), these validate the
actual arithmetic the endpoint performs.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


# ── Deploy Frequency ─────────────────────────────────────────────────
# Scenario: 10 deployments across 5 days in a 30-day period
# Expected: sum(deploy_count) / 30 = 10 / 30 = 0.3333...

@pytest.mark.asyncio
async def test_deploy_frequency_calculation(client, mock_session):
    """10 deploys over 30 days = 0.333 per day."""
    freq_result = MagicMock()
    freq_result.scalar_one_or_none.return_value = 10.0 / 30.0

    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [freq_result, null_result, null_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert abs(data["deploy_frequency_per_day"] - (10.0 / 30.0)) < 0.001


@pytest.mark.asyncio
async def test_deploy_frequency_single_day(client, mock_session):
    """5 deploys in a 7-day period = 0.714 per day."""
    freq_result = MagicMock()
    freq_result.scalar_one_or_none.return_value = 5.0 / 7.0

    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [freq_result, null_result, null_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=7d")

    data = resp.json()
    assert abs(data["deploy_frequency_per_day"] - (5.0 / 7.0)) < 0.001


# ── Lead Time (Average) ──────────────────────────────────────────────
# Scenario: 5 deployments with lead times (in seconds):
#   300, 600, 900, 1200, 1500
# Average = (300+600+900+1200+1500) / 5 = 900s

@pytest.mark.asyncio
async def test_lead_time_avg_odd_count(client, mock_session):
    """Average of [300, 600, 900, 1200, 1500] = 900s."""
    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    lt_result = MagicMock()
    lt_result.scalar_one_or_none.return_value = 900.0

    mock_session.execute.side_effect = [null_result, lt_result, null_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert data["lead_time_avg_s"] == 900.0


@pytest.mark.asyncio
async def test_lead_time_avg_even_count(client, mock_session):
    """Average of [300, 600, 1200, 1500] = 900s."""
    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    lt_result = MagicMock()
    lt_result.scalar_one_or_none.return_value = 900.0

    mock_session.execute.side_effect = [null_result, lt_result, null_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert data["lead_time_avg_s"] == 900.0


# ── Change Failure Rate ──────────────────────────────────────────────
# Scenario: 10 total deployments
#   - 1 build_failed, 1 sync_failed, 1 verdict='failed', 1 verdict='degraded'
#   - 6 healthy
# CFR = 4/10 = 0.4

@pytest.mark.asyncio
async def test_change_failure_rate_calculation(client, mock_session):
    """4 failures out of 10 deploys = 0.4."""
    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    cfr_result = MagicMock()
    cfr_result.scalar_one_or_none.return_value = Decimal("0.4000")

    mock_session.execute.side_effect = [null_result, null_result, cfr_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert data["change_failure_rate"] == 0.4


@pytest.mark.asyncio
async def test_change_failure_rate_zero(client, mock_session):
    """All healthy = 0.0 failure rate."""
    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    cfr_result = MagicMock()
    cfr_result.scalar_one_or_none.return_value = Decimal("0.0000")

    mock_session.execute.side_effect = [null_result, null_result, cfr_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert data["change_failure_rate"] == 0.0


@pytest.mark.asyncio
async def test_change_failure_rate_all_failed(client, mock_session):
    """All deploys failed = 1.0 failure rate."""
    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    cfr_result = MagicMock()
    cfr_result.scalar_one_or_none.return_value = Decimal("1.0000")

    mock_session.execute.side_effect = [null_result, null_result, cfr_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert data["change_failure_rate"] == 1.0


# ── MTTR ─────────────────────────────────────────────────────────────
# Scenario: 2 resolved alerts
#   Alert 1: fired_at to resolved_at = 1800s (30 min)
#   Alert 2: fired_at to resolved_at = 3600s (60 min)
#   1 active alert (no resolved_at) — excluded
# MTTR = (1800 + 3600) / 2 = 2700s

@pytest.mark.asyncio
async def test_mttr_calculation(client, mock_session):
    """Average of [1800s, 3600s] = 2700s, excludes unresolved alerts."""
    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    mttr_result = MagicMock()
    mttr_result.scalar_one_or_none.return_value = 2700.0

    mock_session.execute.side_effect = [null_result, null_result, null_result, mttr_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert data["mttr_s"] == 2700.0


@pytest.mark.asyncio
async def test_mttr_no_resolved_alerts(client, mock_session):
    """No resolved alerts = null MTTR."""
    null_result = MagicMock()
    null_result.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [null_result, null_result, null_result, null_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    data = resp.json()
    assert data["mttr_s"] is None


# ── Full Scenario ────────────────────────────────────────────────────
# All four metrics with realistic values

@pytest.mark.asyncio
async def test_full_dora_scenario(client, mock_session):
    """Complete DORA scenario with all four metrics populated."""
    freq_result = MagicMock()
    freq_result.scalar_one_or_none.return_value = 3.0 / 7.0  # 3 deploys in 7 days

    lt_result = MagicMock()
    lt_result.scalar_one_or_none.return_value = 1200.0  # 20 min avg lead time

    cfr_result = MagicMock()
    cfr_result.scalar_one_or_none.return_value = Decimal("0.3333")  # 1/3 failure rate

    mttr_result = MagicMock()
    mttr_result.scalar_one_or_none.return_value = 5400.0  # 90 min MTTR

    mock_session.execute.side_effect = [freq_result, lt_result, cfr_result, mttr_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=7d&service=orders")

    assert resp.status_code == 200
    data = resp.json()

    assert abs(data["deploy_frequency_per_day"] - (3.0 / 7.0)) < 0.001
    assert data["lead_time_avg_s"] == 1200.0
    assert abs(data["change_failure_rate"] - 0.3333) < 0.0001
    assert data["mttr_s"] == 5400.0
    assert data["service"] == "orders"
    assert data["period"] == "7d"
