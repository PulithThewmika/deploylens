import logging
import os
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

logger = logging.getLogger("deploylens.ingest.grafana")

router = APIRouter(prefix="/api/grafana", tags=["grafana"])

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_SERVICE_ACCOUNT_TOKEN = os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "")

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=GRAFANA_URL, timeout=10.0)
    return _client


@router.get("/proxy")
async def grafana_proxy(
    uid: str,
    panelId: int,
    service: str = Query(default=".*", alias="var-service"),
    from_: str = Query(default="now-6h", alias="from"),
    to: str = Query(default="now"),
    theme: str = Query(default="light"),
):
    """Proxy an embedded Grafana panel (/d-solo/) for the React shell.

    The Grafana service account token is injected server-side and never
    reaches the browser — the shell only ever talks to this endpoint.

    Known limitation: this streams the /d-solo/ HTML through as-is. That
    HTML references Grafana's JS/CSS/API relative to `/`, which 404s once
    served from this proxy's origin instead of Grafana's — the embedded
    panel won't fully render standalone until a follow-up adds either a
    full asset+API reverse proxy (with Grafana configured for a sub-path)
    or switches to the grafana-image-renderer plugin's PNG endpoint.
    """
    params = {
        "panelId": panelId,
        "var-service": service,
        "from": from_,
        "to": to,
        "theme": theme,
    }
    headers = {"Authorization": f"Bearer {GRAFANA_SERVICE_ACCOUNT_TOKEN}"}

    client = _get_client()
    try:
        # uid is escaped before it's spliced into the path — otherwise a
        # uid containing "?"/"&" could inject extra query parameters
        # ahead of the ones set above.
        request = client.build_request(
            "GET", f"/d-solo/{quote(uid, safe='')}", params=params, headers=headers
        )
        upstream = await client.send(request, stream=True)
    except httpx.RequestError:
        logger.exception("Grafana unreachable at %s", GRAFANA_URL)
        raise HTTPException(status_code=502, detail="Grafana unreachable")

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    # Allow-list rather than strip: only content-type is safe/meaningful
    # to forward. This also sidesteps re-sending upstream's
    # content-encoding/content-length, which would mismatch the
    # re-chunked body we're streaming here.
    response_headers = {}
    if "content-type" in upstream.headers:
        response_headers["content-type"] = upstream.headers["content-type"]

    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        headers=response_headers,
    )
