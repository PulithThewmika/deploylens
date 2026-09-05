import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..chat_engine import ANTHROPIC_API_KEY, list_anthropic_tools, run_chat_turn
from ..schemas.chat import ChatRequest

logger = logging.getLogger("kubex.ingest.chat")

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat_proxy(payload: ChatRequest):
    # Pre-flight checks so real connectivity failures return a proper
    # HTTP status instead of a 200 that immediately fails mid-stream.
    # Once StreamingResponse starts, headers are committed — failures
    # after that point become `event: error` SSE frames instead (see
    # chat_engine.run_chat_turn).
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=502, detail="LLM service unavailable")

    try:
        tools = await list_anthropic_tools()
    except Exception:
        logger.exception("MCP server unreachable during chat pre-flight")
        raise HTTPException(status_code=503, detail="MCP server unavailable")

    return StreamingResponse(
        run_chat_turn(payload.messages, tools),
        media_type="text/event-stream",
    )
