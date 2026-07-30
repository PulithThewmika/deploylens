import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from .db import async_session, engine
from .routers import webhooks_github, webhooks_argocd, api, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify DB is reachable on startup
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    await engine.dispose()


app = FastAPI(
    title="DeployLens Ingest",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow React shell origin
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics — namespace/subsystem prefix all metric names as deploylens_ingest_*
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/healthz", "/metrics"],
).instrument(app, metric_namespace="deploylens", metric_subsystem="ingest").expose(app)

# Routers
app.include_router(webhooks_github.router)
app.include_router(webhooks_argocd.router)
app.include_router(api.router)
app.include_router(chat.router)


@app.get("/healthz")
async def healthz():
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}
