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

# Group 1: the bare service name. Group 2: everything after it up to the
# port/path — either nothing (same-namespace, e.g. "orders"), or a dotted
# suffix whose first label is the target namespace (K8s DNS forms
# "orders.billing" and "orders.billing.svc.cluster.local" both start the
# same way).
_URL_RE = re.compile(r"^https?://([a-z0-9-]+)((?:\.[a-z0-9-]+)*)(:\d+)?(/.*)?$", re.IGNORECASE)


def _pod_app_label(deployment: dict) -> str | None:
    return (
        deployment.get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("labels", {})
        .get("app")
    )


def _extract_env_url_targets(deployment: dict, known_service_names: set[str], namespace: str) -> set[str]:
    """Env var values that reference a known Service in this same namespace.

    A namespace-qualified reference (e.g. "orders.billing") to a *different*
    namespace is deliberately skipped rather than resolved against this
    namespace's Service list — matching it against a same-named local
    Service would silently misattribute the edge to the wrong target.
    Cross-namespace discovery isn't supported yet; skipping is safe, a
    wrong edge is not.
    """
    targets: set[str] = set()
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    for container in containers:
        for env_var in container.get("env", []):
            value = env_var.get("value")
            if not value:
                continue
            match = _URL_RE.match(value.strip())
            if not match:
                continue
            host, dotted_suffix = match.group(1), match.group(2)
            target_namespace = dotted_suffix[1:].split(".")[0] if dotted_suffix else namespace
            if target_namespace != namespace:
                continue
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
        for target in _extract_env_url_targets(deployment, known_service_names, namespace):
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
    # A component (e.g. "frontend") is typically the source of several
    # edges in the same namespace — cache its resolved services.id within
    # this run instead of re-querying it once per edge.
    resolved_ids: dict[str, int | None] = {}

    async def resolve_cached(component: str) -> int | None:
        if component not in resolved_ids:
            resolved_ids[component] = await _resolve_service_id(session, component)
        return resolved_ids[component]

    for namespace in namespaces:
        try:
            edges = await discover_namespace_edges(namespace)
        except Exception:
            logger.exception("Blast-radius discovery failed for namespace %s", namespace)
            continue

        for source_component, target_component in edges:
            try:
                # A savepoint, not the outer transaction — a failure here
                # (e.g. a transient DB error) rolls back only this edge,
                # the same isolation pattern webhooks_github.py uses for
                # safety-score writes, so it can't poison the whole
                # session and lose every edge already queued this run.
                async with session.begin_nested():
                    source_id = await resolve_cached(source_component)
                    target_id = await resolve_cached(target_component)
                    if source_id is None or target_id is None:
                        logger.warning(
                            "Skipping edge %s -> %s in namespace %s: component not found in any "
                            "service's prom_components",
                            source_component, target_component, namespace,
                        )
                        continue

                    result = await session.execute(
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
                    # rowcount is 0 when ON CONFLICT DO NOTHING skipped an
                    # already-known edge — only count edges actually
                    # inserted, so this stays meaningful across repeated
                    # 5-minute runs over an unchanged topology.
                    if result.rowcount:
                        written += 1
            except Exception:
                logger.exception(
                    "Failed to persist edge %s -> %s in namespace %s, continuing to next edge",
                    source_component, target_component, namespace,
                )

        logger.info(
            "Blast-radius discovery: namespace=%s edges_found=%d", namespace, len(edges)
        )

    return written
