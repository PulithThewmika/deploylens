"""Core agentic chat loop: Anthropic Messages API + MCP tool calling.

One call to run_chat_turn() handles a full turn, including any number
of tool-use round trips: stream text deltas, and whenever Claude asks
for a tool, call it via MCP, stream the result, and feed it back until
Claude produces a final answer (or the iteration cap is hit).
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator

import anthropic

from .chat_prompt import SYSTEM_PROMPT
from .mcp_client import mcp_session
from .schemas.chat import ChatMessage

logger = logging.getLogger("kubex.ingest.chat_engine")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "claude-sonnet-5")
MAX_TOKENS = 1024
# Guards against a runaway tool-call loop (a model that never stops calling tools).
MAX_TOOL_ITERATIONS = 8


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def list_anthropic_tools() -> list[dict]:
    """Fetch the MCP tool list and convert it to Anthropic's tool schema."""
    async with mcp_session() as session:
        result = await session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.input_schema,
            }
            for tool in result.tools
        ]


async def _call_mcp_tool(name: str, arguments: dict) -> tuple[str, bool]:
    async with mcp_session() as session:
        result = await session.call_tool(name, arguments)
        text = "".join(
            block.text for block in result.content if getattr(block, "text", None)
        )
        return text or "(empty tool result)", result.is_error


def _to_anthropic_messages(messages: list[ChatMessage]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


async def run_chat_turn(
    messages: list[ChatMessage], tools: list[dict]
) -> AsyncIterator[str]:
    """Run one agentic chat turn, yielding SSE frames.

    `tools` is passed in (rather than fetched here) so the caller can
    do the MCP-connectivity pre-flight check before committing to a
    streaming response — see routers/chat.py.
    """
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    current_messages = _to_anthropic_messages(messages)

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            async with client.messages.stream(
                model=CHAT_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=current_messages,
                tools=tools,
            ) as stream:
                async for text in stream.text_stream:
                    yield sse("text", {"text": text})
                final_message = await stream.get_final_message()
        except anthropic.APIError:
            # Headers are already committed to 200 by the time we're
            # streaming, so a mid-stream LLM failure can't become an
            # HTTP 502 — it becomes part of the stream instead. A
            # pre-flight check in routers/chat.py catches the common
            # case (missing API key) before the response starts.
            logger.exception("Anthropic API error mid-stream")
            yield sse("error", {"error": "LLM service unavailable"})
            return

        current_messages.append(
            {
                "role": "assistant",
                "content": [
                    block.model_dump(exclude_none=True)
                    for block in final_message.content
                ],
            }
        )

        if final_message.stop_reason != "tool_use":
            return

        tool_use_blocks = [b for b in final_message.content if b.type == "tool_use"]
        # Claude can request several independent tools in one turn — run
        # them concurrently rather than one round trip at a time.
        outcomes = await asyncio.gather(
            *(_call_mcp_tool(b.name, b.input) for b in tool_use_blocks),
            return_exceptions=True,
        )

        tool_results = []
        for block, outcome in zip(tool_use_blocks, outcomes):
            if isinstance(outcome, BaseException):
                logger.exception(
                    "MCP tool call failed mid-stream: %s", block.name, exc_info=outcome
                )
                yield sse("error", {"error": "MCP server unavailable"})
                return
            result_text, is_error = outcome
            yield sse(
                "tool_call",
                {
                    "tool": block.name,
                    "input": block.input,
                    "result": result_text,
                    "is_error": is_error,
                },
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                    "is_error": is_error,
                }
            )
        current_messages.append({"role": "user", "content": tool_results})

    yield sse(
        "error",
        {"error": "Tool-call loop exceeded maximum iterations without a final answer"},
    )
