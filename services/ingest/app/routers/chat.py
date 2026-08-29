from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat_proxy():
    return {"status": "not_implemented"}
