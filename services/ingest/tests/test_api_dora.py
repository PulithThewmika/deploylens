"""Tests for GET /api/dora endpoint."""

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_dora_returns_all_four_metrics(client, mock_session):
    freq_result = MagicMock()
    freq_result.scalar_one_or_none.return_value = 2.5

    lt_result = MagicMock()
    lt_result.scalar_one_or_none.return_value = 3600.0

    cfr_result = MagicMock()
    cfr_result.scalar_one_or_none.return_value = 0.15

    mttr_result = MagicMock()
    mttr_result.scalar_one_or_none.return_value = 1800.0

    mock_session.execute.side_effect = [freq_result, lt_result, cfr_result, mttr_result]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?period=30d")

    assert resp.status_code == 200
    data = resp.json()
    assert data["deploy_frequency_per_day"] == 2.5
    assert data["lead_time_avg_s"] == 3600.0
    assert data["change_failure_rate"] == 0.15
    assert data["mttr_s"] == 1800.0
    assert data["period"] == "30d"


@pytest.mark.asyncio
async def test_dora_with_service_filter(client, mock_session):
    for _ in range(4):
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
    mock_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        for _ in range(4)
    ]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora?service=orders&period=7d")

    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "orders"
    assert data["period"] == "7d"


@pytest.mark.asyncio
async def test_dora_all_nulls(client, mock_session):
    mock_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        for _ in range(4)
    ]

    async with AsyncClient(transport=ASGITransport(app=client), base_url="http://test") as ac:
        resp = await ac.get("/api/dora")

    assert resp.status_code == 200
    data = resp.json()
    assert data["deploy_frequency_per_day"] is None
    assert data["lead_time_avg_s"] is None
    assert data["change_failure_rate"] is None
    assert data["mttr_s"] is None
