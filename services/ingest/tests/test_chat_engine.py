"""Tests for the chat engine's SSE framing and tool-use loop."""

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.chat_engine import run_chat_turn  # noqa: E402
from app.schemas.chat import ChatMessage  # noqa: E402


def _text_block(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.model_dump.return_value = {"type": "text", "text": text}
    return block


def _tool_use_block(id_, name, input_):
    block = MagicMock()
    block.type = "tool_use"
    block.id = id_
    block.name = name
    block.input = input_
    block.model_dump.return_value = {
        "type": "tool_use",
        "id": id_,
        "name": name,
        "input": input_,
    }
    return block


def _final_message(stop_reason, content):
    message = MagicMock()
    message.stop_reason = stop_reason
    message.content = content
    return message


class _FakeStream:
    def __init__(self, text_chunks, final_message):
        self._text_chunks = text_chunks
        self._final_message = final_message

    @property
    def text_stream(self):
        async def _gen():
            for chunk in self._text_chunks:
                yield chunk

        return _gen()

    async def get_final_message(self):
        return self._final_message


class _FakeStreamManager:
    def __init__(self, stream):
        self._stream = stream

    async def __aenter__(self):
        return self._stream

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_run_chat_turn_streams_text_only():
    final = _final_message("end_turn", [_text_block("Hello there")])
    fake_stream = _FakeStream(["Hello", " there"], final)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _FakeStreamManager(fake_stream)

    with patch("app.chat_engine.anthropic.AsyncAnthropic", return_value=mock_client):
        frames = [
            frame
            async for frame in run_chat_turn(
                [ChatMessage(role="user", content="hi")], tools=[]
            )
        ]

    assert frames == [
        'event: text\ndata: {"text": "Hello"}\n\n',
        'event: text\ndata: {"text": " there"}\n\n',
    ]


@pytest.mark.asyncio
async def test_run_chat_turn_includes_tool_call_results():
    tool_block = _tool_use_block("tool_1", "list_deployments", {"service": "orders"})
    first_final = _final_message("tool_use", [tool_block])
    first_stream = _FakeStream([], first_final)

    second_final = _final_message("end_turn", [_text_block("done")])
    second_stream = _FakeStream(["done"], second_final)

    mock_client = MagicMock()
    mock_client.messages.stream.side_effect = [
        _FakeStreamManager(first_stream),
        _FakeStreamManager(second_stream),
    ]

    mock_mcp_session = AsyncMock()
    mock_mcp_session.call_tool.return_value = MagicMock(
        content=[MagicMock(text='{"deployments": []}')],
        is_error=False,
    )

    @asynccontextmanager
    async def fake_mcp_session():
        yield mock_mcp_session

    with (
        patch("app.chat_engine.anthropic.AsyncAnthropic", return_value=mock_client),
        patch("app.chat_engine.mcp_session", fake_mcp_session),
    ):
        frames = [
            frame
            async for frame in run_chat_turn(
                [ChatMessage(role="user", content="list deploys")], tools=[]
            )
        ]

    assert any(f.startswith("event: tool_call\n") for f in frames)
    tool_call_frame = next(f for f in frames if f.startswith("event: tool_call\n"))
    assert '"tool": "list_deployments"' in tool_call_frame
    assert '"result": "{\\"deployments\\": []}"' in tool_call_frame
    assert frames[-1] == 'event: text\ndata: {"text": "done"}\n\n'
    mock_mcp_session.call_tool.assert_awaited_once_with(
        "list_deployments", {"service": "orders"}
    )


@pytest.mark.asyncio
async def test_run_chat_turn_stops_after_max_iterations():
    tool_block = _tool_use_block("tool_1", "list_deployments", {})
    final = _final_message("tool_use", [tool_block])
    stream = _FakeStream([], final)

    mock_client = MagicMock()
    mock_client.messages.stream.side_effect = lambda **kw: _FakeStreamManager(stream)

    mock_mcp_session = AsyncMock()
    mock_mcp_session.call_tool.return_value = MagicMock(
        content=[MagicMock(text="{}")], is_error=False
    )

    @asynccontextmanager
    async def fake_mcp_session():
        yield mock_mcp_session

    with (
        patch("app.chat_engine.anthropic.AsyncAnthropic", return_value=mock_client),
        patch("app.chat_engine.mcp_session", fake_mcp_session),
    ):
        frames = [
            frame
            async for frame in run_chat_turn(
                [ChatMessage(role="user", content="loop forever")], tools=[]
            )
        ]

    assert frames[-1].startswith("event: error\n")
    assert "maximum iterations" in frames[-1]
