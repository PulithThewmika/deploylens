"""Tests for the pre-deploy safety score formula."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app import safety_score

_NEUTRAL_DAY_TIME = (
    {"value": "Wednesday", "points": 0},
    {"value": "14:00", "points": 0},
)


def _mock_session_with_service(service_name="orders"):
    session = AsyncMock()
    service = MagicMock(name=service_name)
    service.name = service_name
    result = MagicMock()
    result.scalar_one_or_none.return_value = service
    session.execute = AsyncMock(return_value=result)
    return session


class TestDayAndTimeFactors:
    def test_weekday_business_hours_scores_zero(self):
        # Wednesday 2026-08-05, 14:00
        now = datetime(2026, 8, 5, 14, 0)
        day, time = safety_score._day_and_time_factors(now)
        assert day["points"] == 0
        assert time["points"] == 0

    def test_friday_adds_15_points(self):
        # 2026-08-07 is a Friday
        now = datetime(2026, 8, 7, 14, 0)
        day, _ = safety_score._day_and_time_factors(now)
        assert day["points"] == 15

    def test_saturday_adds_15_points(self):
        now = datetime(2026, 8, 8, 14, 0)  # Saturday
        day, _ = safety_score._day_and_time_factors(now)
        assert day["points"] == 15

    def test_outside_business_hours_adds_10_points(self):
        now = datetime(2026, 8, 5, 22, 0)  # Wednesday, 22:00
        _, time = safety_score._day_and_time_factors(now)
        assert time["points"] == 10

    def test_before_business_hours_adds_10_points(self):
        now = datetime(2026, 8, 5, 6, 0)  # Wednesday, 06:00
        _, time = safety_score._day_and_time_factors(now)
        assert time["points"] == 10

    def test_edge_of_business_hours_is_inside(self):
        now = datetime(2026, 8, 5, 8, 0)  # exactly 08:00
        _, time = safety_score._day_and_time_factors(now)
        assert time["points"] == 0


class TestFetchFilesChanged:
    @pytest.mark.asyncio
    async def test_returns_none_without_token(self, monkeypatch):
        monkeypatch.setattr(safety_score, "GITHUB_API_TOKEN", "")
        result = await safety_score._fetch_files_changed("org/repo", "abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self, monkeypatch):
        monkeypatch.setattr(safety_score, "GITHUB_API_TOKEN", "test-token")
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            result = await safety_score._fetch_files_changed("org/repo", "abc123")
            assert result is None


class TestComputeSafetyScore:
    @pytest.mark.asyncio
    async def test_all_factors_clean_scores_zero(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=0.05)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=5)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value="healthy")),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": 20.0, "mem_pct": 30.0})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={"repository": {"full_name": "org/repo"}},
            )
        assert score == 0
        assert factors["cfr_30d"]["points"] == 0
        assert factors["files_changed"]["points"] == 0
        assert factors["cluster_utilization"]["points"] == 0
        assert factors["last_deploy_verdict"]["points"] == 0

    @pytest.mark.asyncio
    async def test_high_cfr_adds_25_points(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=0.20)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=None)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value=None)),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": None, "mem_pct": None})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={},
            )
        assert score == 25
        assert factors["cfr_30d"]["points"] == 25

    @pytest.mark.asyncio
    async def test_files_changed_over_threshold_adds_20_points(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=None)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=45)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value=None)),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": None, "mem_pct": None})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={},
            )
        assert score == 20
        assert factors["files_changed"]["points"] == 20
        assert factors["files_changed"]["value"] == 45

    @pytest.mark.asyncio
    async def test_cluster_cpu_overloaded_adds_15_points(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=None)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=None)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value=None)),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": 80.0, "mem_pct": 30.0})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={},
            )
        assert score == 15
        assert factors["cluster_utilization"]["points"] == 15

    @pytest.mark.asyncio
    async def test_cluster_memory_overloaded_adds_15_points(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=None)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=None)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value=None)),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": 30.0, "mem_pct": 85.0})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={},
            )
        assert score == 15
        assert factors["cluster_utilization"]["points"] == 15

    @pytest.mark.asyncio
    async def test_last_deploy_degraded_adds_15_points(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=None)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=None)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value="degraded")),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": None, "mem_pct": None})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={},
            )
        assert score == 15
        assert factors["last_deploy_verdict"]["points"] == 15

    @pytest.mark.asyncio
    async def test_last_deploy_failed_adds_15_points(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=None)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=None)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value="failed")),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": None, "mem_pct": None})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={},
            )
        assert score == 15

    @pytest.mark.asyncio
    async def test_all_factors_triggered_scores_exactly_100(self):
        session = _mock_session_with_service()
        with (
            patch.object(safety_score, "_query_cfr_30d", AsyncMock(return_value=0.50)),
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=100)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value="failed")),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": 99.0, "mem_pct": 99.0})),
            patch.object(safety_score, "_day_and_time_factors", return_value=(
                {"value": "Friday", "points": 15}, {"value": "22:00", "points": 10},
            )),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=1, commit_sha="abc1234", payload={},
            )
        assert score == 100

    @pytest.mark.asyncio
    async def test_missing_service_skips_cfr_but_does_not_crash(self):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        with (
            patch.object(safety_score, "_fetch_files_changed", AsyncMock(return_value=None)),
            patch.object(safety_score, "_query_last_verdict", AsyncMock(return_value=None)),
            patch.object(safety_score, "fetch_cluster_utilization", AsyncMock(return_value={"cpu_pct": None, "mem_pct": None})),
            patch.object(safety_score, "_day_and_time_factors", return_value=_NEUTRAL_DAY_TIME),
        ):
            score, factors = await safety_score.compute_safety_score(
                session, service_id=999, commit_sha="abc1234", payload={},
            )
        assert factors["cfr_30d"]["value"] is None
        assert factors["cfr_30d"]["points"] == 0
