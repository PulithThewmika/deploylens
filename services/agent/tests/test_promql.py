"""Tests for PromQL query builders and Prometheus client."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent.promql import (
    _sanitize_label,
    query_prometheus,
    query_error_rate,
    query_latency_p99,
    query_restarts,
    query_request_rate,
)


def _make_prom_response(value: float) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1722700000, str(value)]}],
        },
    }


def _make_empty_response() -> dict:
    return {
        "status": "success",
        "data": {"resultType": "vector", "result": []},
    }


TS = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response with sync json() and raise_for_status()."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def mock_client():
    """Create a mock httpx client for Prometheus queries."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.is_closed = False
    with patch("agent.promql._client", client):
        yield client


@pytest.mark.asyncio
async def test_query_prometheus_valid_data(mock_client):
    """Valid Prometheus response returns correct float."""
    mock_client.get.return_value = _mock_response(_make_prom_response(0.042))

    result = await query_prometheus("up", TS)
    assert result == pytest.approx(0.042)
    mock_client.get.assert_called_once_with(
        "/api/v1/query",
        params={"query": "up", "time": TS.timestamp()},
    )


@pytest.mark.asyncio
async def test_query_prometheus_empty_result(mock_client):
    """Empty result set returns None."""
    mock_client.get.return_value = _mock_response(_make_empty_response())

    result = await query_prometheus("up", TS)
    assert result is None


@pytest.mark.asyncio
async def test_query_prometheus_nan_result(mock_client):
    """NaN result returns None."""
    mock_client.get.return_value = _mock_response(_make_prom_response(float("nan")))

    result = await query_prometheus("up", TS)
    assert result is None


@pytest.mark.asyncio
async def test_query_prometheus_unreachable(mock_client):
    """Prometheus unreachable returns None with warning."""
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")

    result = await query_prometheus("up", TS)
    assert result is None


@pytest.mark.asyncio
async def test_query_prometheus_timeout(mock_client, caplog):
    """Prometheus timeout returns None and logs a warning."""
    mock_client.get.side_effect = httpx.TimeoutException("Timed out")

    with caplog.at_level("WARNING", logger="kubex.agent.promql"):
        result = await query_prometheus("up", TS)

    assert result is None
    assert any("Prometheus unreachable" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_query_error_rate(mock_client):
    """Error rate query constructs correct PromQL and returns float."""
    mock_client.get.return_value = _mock_response(_make_prom_response(0.03))

    result = await query_error_rate("orders", "kubex", "30m", TS)
    assert result == pytest.approx(0.03)

    call_args = mock_client.get.call_args
    query = call_args.kwargs["params"]["query"]
    assert 'service="orders"' in query
    assert 'namespace="kubex"' in query
    assert 'status=~"5.."' in query
    assert "[30m]" in query


@pytest.mark.asyncio
async def test_query_latency_p99_converts_to_ms(mock_client):
    """Latency query returns value converted from seconds to milliseconds."""
    mock_client.get.return_value = _mock_response(_make_prom_response(0.25))

    result = await query_latency_p99("orders", "kubex", "15m", TS)
    assert result == pytest.approx(250.0)

    call_args = mock_client.get.call_args
    query = call_args.kwargs["params"]["query"]
    assert "histogram_quantile(0.99" in query
    assert "[15m]" in query


@pytest.mark.asyncio
async def test_query_restarts(mock_client):
    """Restart query constructs correct PromQL with container label."""
    mock_client.get.return_value = _mock_response(_make_prom_response(2.0))

    result = await query_restarts("payments", "kubex", "30m", TS)
    assert result == pytest.approx(2.0)

    call_args = mock_client.get.call_args
    query = call_args.kwargs["params"]["query"]
    assert "kube_pod_container_status_restarts_total" in query
    assert 'container="payments"' in query


def test_sanitize_label_clean_value():
    """Normal service name passes through unchanged."""
    assert _sanitize_label("orders") == "orders"


def test_sanitize_label_escapes_double_quote():
    """Double quotes are escaped to prevent PromQL injection."""
    assert _sanitize_label('x"} or vector(1)') == 'x\\"} or vector(1)'


def test_sanitize_label_escapes_backslash():
    """Backslashes are escaped."""
    assert _sanitize_label("a\\b") == "a\\\\b"


def test_sanitize_label_escapes_newlines():
    """Newlines and carriage returns are escaped."""
    assert _sanitize_label("a\nb\r") == "a\\\nb\\\r"


@pytest.mark.asyncio
async def test_query_error_rate_sanitizes_service(mock_client):
    """Service names with injection characters are escaped in PromQL."""
    mock_client.get.return_value = _mock_response(_make_prom_response(0.01))

    await query_error_rate('x"} or vector(1){a="', "kubex", "30m", TS)

    query = mock_client.get.call_args.kwargs["params"]["query"]
    assert 'service="x\\"} or vector(1){a=\\"' in query
