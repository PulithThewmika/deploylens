import asyncio
import os
import random

import httpx
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import Info
from starlette.middleware.base import BaseHTTPMiddleware

SERVICE_NAME = os.getenv("SERVICE_NAME", "frontend")
ERROR_RATE = float(os.getenv("ERROR_RATE", "0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))
ORDERS_URL = os.getenv("ORDERS_URL", "http://orders:8000")

app = FastAPI(title="Frontend Service")


# ── Chaos middleware ────────────────────────────────────────────────

class ChaosMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/metrics", "/healthz"):
            return await call_next(request)

        if LATENCY_MS > 0:
            await asyncio.sleep(LATENCY_MS / 1000.0)

        if ERROR_RATE > 0 and random.random() < ERROR_RATE:
            return Response(
                content='{"detail":"chaos: injected error"}',
                status_code=500,
                media_type="application/json",
            )

        return await call_next(request)


app.add_middleware(ChaosMiddleware)


# ── Prometheus instrumentation with service label ───────────────────

_requests_counter = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "handler", "status"],
)

_duration_histogram = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "method", "handler", "status"],
)


def _count_requests(info: Info) -> None:
    _requests_counter.labels(
        service=SERVICE_NAME,
        method=info.request.method,
        handler=info.modified_handler,
        status=info.modified_status,
    ).inc()


def _observe_duration(info: Info) -> None:
    _duration_histogram.labels(
        service=SERVICE_NAME,
        method=info.request.method,
        handler=info.modified_handler,
        status=info.modified_status,
    ).observe(info.modified_duration)


instrumentator = Instrumentator(
    should_instrument_requests_inprogress=False,
    excluded_handlers=["/metrics", "/healthz"],
)
instrumentator.add(_count_requests)
instrumentator.add(_observe_duration)
instrumentator.instrument(app).expose(app)


# ── Routes ──────────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/")
async def index():
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ORDERS_URL}/orders")
        order = resp.json()

    return {
        "service": "frontend",
        "order": order,
    }
