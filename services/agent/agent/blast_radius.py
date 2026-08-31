"""Blast-radius dependency discovery (E14-T3).

Discovery mechanism: list each monitored namespace's K8s Services (to get
the set of valid in-cluster DNS names) and Deployments (to inspect each
container's env vars), then match env var values shaped like
`http(s)://<service-name>[.<namespace>][:<port>][/...]` against the known
Service names. A match means "this pod calls that service" — e.g. the
sample app's frontend Deployment has `ORDERS_URL=http://orders:8000`,
which resolves to the `orders` Service.

Component-to-service mapping goes through services.prom_components (already
used to map Prometheus's per-microservice labels back to one services row
per ArgoCD app — see V005) rather than a new namespace/app convention,
since it already captures exactly "these K8s-level names belong to this
services row."
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import text

from .k8s_client import list_deployments, list_services

logger = logging.getLogger("deploylens.agent.blast_radius")

_URL_RE = re.compile(r"^https?://([a-z0-9-]+)(\.[a-z0-9-]+)?(:\d+)?(/.*)?$", re.IGNORECASE)


def _pod_app_label(deployment: dict) -> str | None:
    return (
        deployment.get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("labels", {})
        .get("app")
    )


def _extract_env_url_targets(deployment: dict, known_service_names: set[str]) -> set[str]:
    """Env var values that reference a known in-cluster Service by name."""
    targets: set[str] = set()
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    for container in containers:
        for env_var in container.get("env", []):
            value = env_var.get("value")
            if not value:
                continue
            match = _URL_RE.match(value.strip())
            if match:
                host = match.group(1)
                if host in known_service_names:
                    targets.add(host)
    return targets


async def discover_namespace_edges(namespace: str) -> list[tuple[str, str]]:
    """Return (source_component, target_component) edges found in one namespace."""
    services = await list_services(namespace)
    deployments = await list_deployments(namespace)

    known_service_names = {s["metadata"]["name"] for s in services}

    edges: list[tuple[str, str]] = []
    for deployment in deployments:
        source = _pod_app_label(deployment)
        if not source:
            continue
        for target in _extract_env_url_targets(deployment, known_service_names):
            if target != source:
                edges.append((source, target))

    return edges


async def get_monitored_namespaces(session) -> list[str]:
    result = await session.execute(
        text("SELECT DISTINCT namespace FROM services WHERE prom_components IS NOT NULL")
    )
    return [row.namespace for row in result.fetchall()]


async def _resolve_service_id(session, component: str) -> int | None:
    result = await session.execute(
        text("SELECT id FROM services WHERE :component = ANY(prom_components)"),
        {"component": component},
    )
    row = result.first()
    return row.id if row else None


async def run_discovery(session, namespaces: list[str]) -> int:
    """Discover dependencies across the given namespaces and upsert edges.

    Returns the number of edges written.
    """
    written = 0
    for namespace in namespaces:
        try:
            edges = await discover_namespace_edges(namespace)
        except Exception:
            logger.exception("Blast-radius discovery failed for namespace %s", namespace)
            continue

        for source_component, target_component in edges:
            source_id = await _resolve_service_id(session, source_component)
            target_id = await _resolve_service_id(session, target_component)
            if source_id is None or target_id is None:
                logger.warning(
                    "Skipping edge %s -> %s in namespace %s: component not found in any "
                    "service's prom_components",
                    source_component, target_component, namespace,
                )
                continue

            await session.execute(
                text("""
                    INSERT INTO service_dependencies
                        (source_id, target_id, dep_type, source_component, target_component)
                    VALUES (:source_id, :target_id, 'calls', :source_component, :target_component)
                    ON CONFLICT (source_id, target_id, dep_type, source_component, target_component)
                    DO NOTHING
                """),
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "source_component": source_component,
                    "target_component": target_component,
                },
            )
            written += 1

        logger.info(
            "Blast-radius discovery: namespace=%s edges_found=%d", namespace, len(edges)
        )

    return written
