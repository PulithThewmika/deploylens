"""Tests for POST /api/chat error handling and streaming."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_chat_returns_502_when_api_key_missing(client):
    with patch("app.routers.chat.ANTHROPIC_API_KEY", ""):
        async with AsyncClient(
            transport=ASGITransport(app=client), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}
            )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "LLM service unavailable"
    assert "test-key" not in resp.text
    assert "ANTHROPIC_API_KEY" not in resp.headers


@pytest.mark.asyncio
async def test_chat_returns_503_when_mcp_unreachable(client):
    with (
        patch("app.routers.chat.ANTHROPIC_API_KEY", "test-key"),
        patch(
            "app.routers.chat.list_anthropic_tools",
            side_effect=ConnectionError("mcp-server unreachable"),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=client), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}
            )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "MCP server unavailable"


@pytest.mark.asyncio
async def test_chat_streams_sse_response(client):
    async def fake_run_chat_turn(messages, tools):
        yield 'event: text\ndata: {"text": "hi"}\n\n'

    with (
        patch("app.routers.chat.ANTHROPIC_API_KEY", "test-key"),
        patch("app.routers.chat.list_anthropic_tools", return_value=[]),
        patch("app.routers.chat.run_chat_turn", fake_run_chat_turn),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=client), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.text == 'event: text\ndata: {"text": "hi"}\n\n'
    assert "test-key" not in resp.text
    assert "ANTHROPIC_API_KEY" not in resp.headers
