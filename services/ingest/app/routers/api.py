from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/services")
async def list_services():
    return {"status": "not_implemented"}


@router.get("/deployments")
async def list_deployments():
    return {"status": "not_implemented"}
