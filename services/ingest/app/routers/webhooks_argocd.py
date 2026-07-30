from fastapi import APIRouter

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/argocd")
async def argocd_webhook():
    return {"status": "not_implemented"}
