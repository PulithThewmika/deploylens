from fastapi import APIRouter

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/")
async def chat_proxy():
    return {"status": "not_implemented"}
