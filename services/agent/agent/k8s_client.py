"""Minimal read-only Kubernetes API client for blast-radius discovery.

Talks to the K8s API server directly over HTTPS with a ServiceAccount
bearer token (minted by deploy/scripts/create-blast-radius-sa.sh) instead
of pulling in the full kubernetes python client — the agent only ever
needs to list Services and Deployments in one namespace.

Hostname verification is disabled (but certificate-chain verification
against the cluster's real CA is not) because the agent runs outside the
cluster in docker-compose and reaches the Kind API server via
host.docker.internal, which the API server's certificate has no SAN for —
the same cross-boundary-access pattern already used for PROM_URL/
ALERTMANAGER_URL in this project (see config.py), just also over TLS here.
"""

from __future__ import annotations

import base64
import logging
import ssl
import tempfile

import httpx

from .config import K8S_API_SERVER, K8S_CA_CERT_B64, K8S_TOKEN

logger = logging.getLogger("kubex.agent.k8s_client")

_client: httpx.AsyncClient | None = None


def blast_radius_enabled() -> bool:
    return bool(K8S_API_SERVER and K8S_TOKEN and K8S_CA_CERT_B64)


def _build_ssl_context() -> ssl.SSLContext:
    # ssl.create_default_context(cafile=...) reads and parses the file
    # synchronously during this call — nothing holds the path open
    # afterward, so the temp file is deleted immediately rather than
    # leaking one on every client (re)creation.
    with tempfile.NamedTemporaryFile(suffix=".crt") as ca_cert_file:
        ca_cert_file.write(base64.b64decode(K8S_CA_CERT_B64))
        ca_cert_file.flush()
        ssl_context = ssl.create_default_context(cafile=ca_cert_file.name)
    ssl_context.check_hostname = False
    return ssl_context


def get_k8s_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=K8S_API_SERVER,
            headers={"Authorization": f"Bearer {K8S_TOKEN}"},
            verify=_build_ssl_context(),
            timeout=10.0,
        )
    return _client


async def close_k8s_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def list_services(namespace: str) -> list[dict]:
    client = get_k8s_client()
    resp = await client.get(f"/api/v1/namespaces/{namespace}/services")
    resp.raise_for_status()
    return resp.json().get("items", [])


async def list_deployments(namespace: str) -> list[dict]:
    client = get_k8s_client()
    resp = await client.get(f"/apis/apps/v1/namespaces/{namespace}/deployments")
    resp.raise_for_status()
    return resp.json().get("items", [])
