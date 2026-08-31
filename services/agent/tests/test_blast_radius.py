"""Tests for blast-radius dependency discovery (E14-T3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.blast_radius import (
    _extract_env_url_targets,
    _pod_app_label,
    discover_namespace_edges,
    get_monitored_namespaces,
    run_discovery,
)


def _deployment(app_label: str, env: list[dict]) -> dict:
    return {
        "spec": {
            "template": {
                "metadata": {"labels": {"app": app_label}},
                "spec": {"containers": [{"env": env}]},
            }
        }
    }


def _service(name: str) -> dict:
    return {"metadata": {"name": name}}


class TestExtractEnvUrlTargets:
    def test_matches_url_env_var_referencing_known_service(self):
        deployment = _deployment("frontend", [{"name": "ORDERS_URL", "value": "http://orders:8000"}])
        targets = _extract_env_url_targets(deployment, {"orders", "payments"})
        assert targets == {"orders"}

    def test_ignores_url_not_matching_a_known_service(self):
        deployment = _deployment("frontend", [{"name": "EXTERNAL_URL", "value": "http://example.com"}])
        targets = _extract_env_url_targets(deployment, {"orders", "payments"})
        assert targets == set()

    def test_ignores_non_url_env_vars(self):
        deployment = _deployment("frontend", [{"name": "ERROR_RATE", "value": "0"}])
        targets = _extract_env_url_targets(deployment, {"orders"})
        assert targets == set()

    def test_handles_missing_env_value(self):
        deployment = _deployment("frontend", [{"name": "SOME_VAR"}])
        targets = _extract_env_url_targets(deployment, {"orders"})
        assert targets == set()


class TestPodAppLabel:
    def test_extracts_app_label(self):
        deployment = _deployment("orders", [])
        assert _pod_app_label(deployment) == "orders"

    def test_returns_none_when_missing(self):
        assert _pod_app_label({"spec": {"template": {"metadata": {"labels": {}}}}}) is None


class TestDiscoverNamespaceEdges:
    @pytest.mark.asyncio
    async def test_discovers_the_sample_app_chain(self):
        """frontend -> orders -> payments, matching the real sample app config."""
        services = [_service("frontend"), _service("orders"), _service("payments"), _service("loadgen")]
        deployments = [
            _deployment("frontend", [{"name": "ORDERS_URL", "value": "http://orders:8000"}]),
            _deployment("orders", [{"name": "PAYMENTS_URL", "value": "http://payments:8000"}]),
            _deployment("payments", []),
        ]

        with patch("agent.blast_radius.list_services", AsyncMock(return_value=services)), \
             patch("agent.blast_radius.list_deployments", AsyncMock(return_value=deployments)):
            edges = await discover_namespace_edges("deploylens")

        assert set(edges) == {("frontend", "orders"), ("orders", "payments")}

    @pytest.mark.asyncio
    async def test_skips_deployments_with_no_app_label(self):
        with patch("agent.blast_radius.list_services", AsyncMock(return_value=[_service("orders")])), \
             patch("agent.blast_radius.list_deployments", AsyncMock(return_value=[{"spec": {"template": {"metadata": {"labels": {}}, "spec": {"containers": []}}}}])):
            edges = await discover_namespace_edges("deploylens")
        assert edges == []

    @pytest.mark.asyncio
    async def test_excludes_self_referencing_edges(self):
        deployments = [_deployment("orders", [{"name": "SELF_URL", "value": "http://orders:8000"}])]
        with patch("agent.blast_radius.list_services", AsyncMock(return_value=[_service("orders")])), \
             patch("agent.blast_radius.list_deployments", AsyncMock(return_value=deployments)):
            edges = await discover_namespace_edges("deploylens")
        assert edges == []


class TestGetMonitoredNamespaces:
    @pytest.mark.asyncio
    async def test_returns_distinct_namespaces(self):
        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = [MagicMock(namespace="deploylens")]
        session.execute.return_value = result

        namespaces = await get_monitored_namespaces(session)
        assert namespaces == ["deploylens"]


class TestRunDiscovery:
    @pytest.mark.asyncio
    async def test_writes_edges_and_resolves_service_ids_via_prom_components(self):
        session = AsyncMock()

        def _resolve_result(component):
            row = MagicMock()
            row.id = 31
            return row

        # First two execute() calls resolve source_id/target_id per edge,
        # then the INSERT itself.
        results = [MagicMock(first=lambda: _resolve_result("frontend")),
                   MagicMock(first=lambda: _resolve_result("orders")),
                   MagicMock()]
        session.execute = AsyncMock(side_effect=results)

        with patch("agent.blast_radius.discover_namespace_edges", AsyncMock(return_value=[("frontend", "orders")])):
            written = await run_discovery(session, ["deploylens"])

        assert written == 1

    @pytest.mark.asyncio
    async def test_skips_edge_when_component_not_in_any_prom_components(self):
        session = AsyncMock()
        # Both lookups return no match.
        session.execute = AsyncMock(return_value=MagicMock(first=lambda: None))

        with patch("agent.blast_radius.discover_namespace_edges", AsyncMock(return_value=[("loadgen", "frontend")])):
            written = await run_discovery(session, ["deploylens"])

        assert written == 0

    @pytest.mark.asyncio
    async def test_continues_to_next_namespace_on_discovery_failure(self):
        session = AsyncMock()
        with patch(
            "agent.blast_radius.discover_namespace_edges",
            AsyncMock(side_effect=[Exception("K8s API unreachable"), []]),
        ):
            written = await run_discovery(session, ["ns-a", "ns-b"])
        assert written == 0
