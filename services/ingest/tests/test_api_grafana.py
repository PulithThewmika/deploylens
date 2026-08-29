"""Tests for GET /api/grafana/proxy."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient


def _mock_upstream(status_code=200, content_type="text/html; charset=UTF-8", chunks=None):
    chunks = chunks or [b"<html>panel</html>"]
    upstream = MagicMock()
    upstream.status_code = status_code
    upstream.headers = {"content-type": content_type} if content_type else {}
    upstream.aclose = AsyncMock()

    async def aiter_bytes():
        for chunk in chunks:
            yield chunk

    upstream.aiter_bytes = aiter_bytes
    return upstream


@pytest.mark.asyncio
async def test_proxy_returns_grafana_panel_html(client):
    upstream = _mock_upstream(chunks=[b"<html>", b"panel", b"</html>"])
    mock_httpx_client = MagicMock()
    mock_httpx_client.build_request = MagicMock(return_value="fake-request")
    mock_httpx_client.send = AsyncMock(return_value=upstream)

    with (
        patch("app.routers.grafana.GRAFANA_SERVICE_ACCOUNT_TOKEN", "super-secret-token"),
        patch("app.routers.grafana._get_client", return_value=mock_httpx_client),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=client), base_url="http://test"
        ) as ac:
            resp = await ac.get(
                "/api/grafana/proxy",
                params={"uid": "deploy-timeline", "panelId": 1},
            )

    assert resp.status_code == 200
    assert resp.text == "<html>panel</html>"
    assert resp.headers["content-type"] == "text/html; charset=UTF-8"

    # The token was forwarded to Grafana, not to the browser.
    sent_request_kwargs = mock_httpx_client.build_request.call_args
    assert (
        sent_request_kwargs.kwargs["headers"]["Authorization"]
        == "Bearer super-secret-token"
    )
    assert "super-secret-token" not in resp.text
    assert "authorization" not in {h.lower() for h in resp.headers}


@pytest.mark.asyncio
async def test_proxy_escapes_uid_before_building_url(client):
    upstream = _mock_upstream()
    mock_httpx_client = MagicMock()
    mock_httpx_client.build_request = MagicMock(return_value="fake-request")
    mock_httpx_client.send = AsyncMock(return_value=upstream)

    with patch("app.routers.grafana._get_client", return_value=mock_httpx_client):
        async with AsyncClient(
            transport=ASGITransport(app=client), base_url="http://test"
        ) as ac:
            await ac.get(
                "/api/grafana/proxy",
                params={"uid": "deploy-timeline?from=0&to=999", "panelId": 1},
            )

    sent_args = mock_httpx_client.build_request.call_args
    url_path = sent_args.args[1]
    assert url_path == "/d-solo/deploy-timeline%3Ffrom%3D0%26to%3D999"


@pytest.mark.asyncio
async def test_proxy_returns_502_when_grafana_unreachable(client):
    mock_httpx_client = MagicMock()
    mock_httpx_client.build_request = MagicMock(return_value="fake-request")
    mock_httpx_client.send = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with patch("app.routers.grafana._get_client", return_value=mock_httpx_client):
        async with AsyncClient(
            transport=ASGITransport(app=client), base_url="http://test"
        ) as ac:
            resp = await ac.get(
                "/api/grafana/proxy",
                params={"uid": "deploy-timeline", "panelId": 1},
            )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "Grafana unreachable"
