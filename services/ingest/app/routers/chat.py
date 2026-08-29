from fastapi import APIRouter

from ..schemas.chat import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat_proxy(payload: ChatRequest):
    return {"status": "not_implemented"}
