from fastapi import FastAPI

app = FastAPI(title="DeployLens Ingest", version="0.1.0")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
