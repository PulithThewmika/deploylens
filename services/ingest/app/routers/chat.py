from fastapi.responses import StreamingResponse
from fastapi import APIRouter

from ..chat_engine import list_anthropic_tools, run_chat_turn
from ..schemas.chat import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat_proxy(payload: ChatRequest):
    tools = await list_anthropic_tools()

    return StreamingResponse(
        run_chat_turn(payload.messages, tools),
        media_type="text/event-stream",
    )
