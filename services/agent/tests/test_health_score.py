"""Tests for health score formula — doc 05 exact implementation."""

from __future__ import annotations

import pytest

from agent.health_score import clamp, penalty, compute_health_score


# ── clamp ────────────────────────────────────────────────────────────

class TestClamp:
    def test_within_range(self):
        assert clamp(0.5, 0, 1) == 0.5

    def test_below_min(self):
        assert clamp(-0.5, 0, 1) == 0.0

    def test_above_max(self):
        assert clamp(1.5, 0, 1) == 1.0

    def test_at_boundaries(self):
        assert clamp(0.0, 0, 1) == 0.0
        assert clamp(1.0, 0, 1) == 1.0


# ── penalty ──────────────────────────────────────────────────────────

class TestPenalty:
    # error_rate: clamp((post - base) / 0.05, 0, 1)
    def test_error_rate_no_change(self):
        assert penalty(0.01, 0.01, "error_rate") == pytest.approx(0.0)

    def test_error_rate_small_increase(self):
        # delta = 0.02, penalty = 0.02/0.05 = 0.4
        assert penalty(0.01, 0.03, "error_rate") == pytest.approx(0.4)

    def test_error_rate_large_increase(self):
        # delta = 0.10, penalty = 0.10/0.05 = 2.0, clamped to 1.0
        assert penalty(0.01, 0.11, "error_rate") == pytest.approx(1.0)

    def test_error_rate_decrease(self):
        # delta = -0.02, clamped to 0
        assert penalty(0.05, 0.03, "error_rate") == pytest.approx(0.0)

    # latency_p99: clamp((post/base - 1.2) / 1.8, 0, 1)
    def test_latency_no_change(self):
        # ratio = 1.0, (1.0 - 1.2) / 1.8 = -0.111, clamped to 0
        assert penalty(100.0, 100.0, "latency_p99") == pytest.approx(0.0)

    def test_latency_moderate_increase(self):
        # ratio = 1.5, (1.5 - 1.2) / 1.8 = 0.1667
        assert penalty(100.0, 150.0, "latency_p99") == pytest.approx(0.1667, abs=0.001)

    def test_latency_3x_increase(self):
        # ratio = 3.0, (3.0 - 1.2) / 1.8 = 1.0
        assert penalty(100.0, 300.0, "latency_p99") == pytest.approx(1.0)

    def test_latency_zero_baseline(self):
        """Zero baseline latency should return 0 penalty (division guard)."""
        assert penalty(0.0, 100.0, "latency_p99") == pytest.approx(0.0)

    def test_latency_none_values(self):
        assert penalty(None, 100.0, "latency_p99") == pytest.approx(0.0)
        assert penalty(100.0, None, "latency_p99") == pytest.approx(0.0)

    # restarts: clamp((post - base) / 3.0, 0, 1)
    def test_restarts_none(self):
        assert penalty(0.0, 0.0, "restarts") == pytest.approx(0.0)

    def test_restarts_one(self):
        # delta = 1, 1/3 = 0.333
        assert penalty(0.0, 1.0, "restarts") == pytest.approx(0.333, abs=0.001)

    def test_restarts_three(self):
        # delta = 3, 3/3 = 1.0
        assert penalty(0.0, 3.0, "restarts") == pytest.approx(1.0)

    def test_restarts_four(self):
        # delta = 4, 4/3 = 1.333, clamped to 1.0
        assert penalty(1.0, 5.0, "restarts") == pytest.approx(1.0)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            penalty(0.0, 1.0, "unknown")


# ── compute_health_score ─────────────────────────────────────────────

class TestComputeHealthScore:
    def test_healthy_deployment(self):
        """Low error rate, stable latency, no restarts -> score >= 80."""
        metrics = {
            "error_rate_base": 0.01,
            "error_rate_post": 0.01,
            "latency_p99_base_ms": 100.0,
            "latency_p99_post_ms": 105.0,
            "restarts_base": 0.0,
            "restarts_post": 0.0,
            "request_rate_base": 10.0,
            "request_rate_post": 10.0,
        }
        score, verdict, details = compute_health_score(metrics)
        assert score >= 80
        assert verdict == "healthy"
        assert details["low_traffic"] is False

    def test_degraded_deployment(self):
        """Error rate +3pp, latency +50% -> score 50-79."""
        metrics = {
            "error_rate_base": 0.01,
            "error_rate_post": 0.04,  # +3pp => penalty = 0.03/0.05 = 0.6
            "latency_p99_base_ms": 100.0,
            "latency_p99_post_ms": 150.0,  # ratio 1.5 => penalty = (1.5-1.2)/1.8 = 0.167
            "restarts_base": 0.0,
            "restarts_post": 0.0,
            "request_rate_base": 10.0,
            "request_rate_post": 10.0,
        }
        score, verdict, details = compute_health_score(metrics)
        # 100 - (45*0.6 + 30*0.167 + 25*0) = 100 - (27 + 5) = 68
        assert 50 <= score <= 79
        assert verdict == "degraded"

    def test_failed_deployment(self):
        """Error rate +5pp, latency 3x, 4 restarts -> score < 50."""
        metrics = {
            "error_rate_base": 0.01,
            "error_rate_post": 0.06,  # +5pp => penalty = 1.0
            "latency_p99_base_ms": 100.0,
            "latency_p99_post_ms": 300.0,  # 3x => penalty = 1.0
            "restarts_base": 0.0,
            "restarts_post": 4.0,  # 4 restarts => penalty = 1.0
            "request_rate_base": 10.0,
            "request_rate_post": 10.0,
        }
        score, verdict, details = compute_health_score(metrics)
        # 100 - (45*1 + 30*1 + 25*1) = 100 - 100 = 0
        assert score < 50
        assert verdict == "failed"

    def test_low_traffic_skips_error_latency_penalties(self):
        """Low traffic (< 0.1 rps) skips error/latency penalties, noted in details."""
        metrics = {
            "error_rate_base": 0.5,  # would be huge penalty normally
            "error_rate_post": 0.9,
            "latency_p99_base_ms": 100.0,
            "latency_p99_post_ms": 5000.0,
            "restarts_base": 0.0,
            "restarts_post": 0.0,
            "request_rate_base": 0.05,
            "request_rate_post": 0.08,
        }
        score, verdict, details = compute_health_score(metrics)
        assert details["low_traffic"] is True
        assert details["penalties"]["error_rate"] == 0.0
        assert details["penalties"]["latency_p99"] == 0.0
        assert "skip_reasons" in details
        assert score >= 80  # only restarts penalty applies (0), so score = 100

    def test_low_traffic_with_none_rps(self):
        """None rps counts as low traffic."""
        metrics = {
            "error_rate_base": 0.5,
            "error_rate_post": 0.9,
            "latency_p99_base_ms": 100.0,
            "latency_p99_post_ms": 5000.0,
            "restarts_base": 0.0,
            "restarts_post": 0.0,
            "request_rate_base": None,
            "request_rate_post": None,
        }
        score, verdict, details = compute_health_score(metrics)
        assert details["low_traffic"] is True
        assert score >= 80

    def test_zero_baseline_latency(self):
        """Zero baseline latency -> latency penalty = 0 (division guard)."""
        metrics = {
            "error_rate_base": 0.0,
            "error_rate_post": 0.0,
            "latency_p99_base_ms": 0.0,
            "latency_p99_post_ms": 500.0,
            "restarts_base": 0.0,
            "restarts_post": 0.0,
            "request_rate_base": 10.0,
            "request_rate_post": 10.0,
        }
        score, verdict, details = compute_health_score(metrics)
        assert details["penalties"]["latency_p99"] == 0.0

    def test_all_component_values_in_details(self):
        """Verify all component values are present in output dict."""
        metrics = {
            "error_rate_base": 0.01,
            "error_rate_post": 0.02,
            "latency_p99_base_ms": 100.0,
            "latency_p99_post_ms": 120.0,
            "restarts_base": 0.0,
            "restarts_post": 1.0,
            "request_rate_base": 5.0,
            "request_rate_post": 5.0,
        }
        score, verdict, details = compute_health_score(metrics)
        assert "penalties" in details
        assert "weights" in details
        assert "weighted_sum" in details
        assert "low_traffic" in details
        assert "raw_metrics" in details

        raw = details["raw_metrics"]
        for key in [
            "error_rate_base", "error_rate_post",
            "latency_p99_base_ms", "latency_p99_post_ms",
            "restarts_base", "restarts_post",
        ]:
            assert key in raw

    def test_perfect_score(self):
        """All metrics identical pre/post -> score 100."""
        metrics = {
            "error_rate_base": 0.01,
            "error_rate_post": 0.01,
            "latency_p99_base_ms": 100.0,
            "latency_p99_post_ms": 100.0,
            "restarts_base": 0.0,
            "restarts_post": 0.0,
            "request_rate_base": 10.0,
            "request_rate_post": 10.0,
        }
        score, verdict, details = compute_health_score(metrics)
        assert score == 100
        assert verdict == "healthy"

    def test_score_clamped_to_zero(self):
        """Extreme degradation doesn't go below 0."""
        metrics = {
            "error_rate_base": 0.0,
            "error_rate_post": 1.0,
            "latency_p99_base_ms": 10.0,
            "latency_p99_post_ms": 10000.0,
            "restarts_base": 0.0,
            "restarts_post": 100.0,
            "request_rate_base": 10.0,
            "request_rate_post": 10.0,
        }
        score, verdict, details = compute_health_score(metrics)
        assert score == 0
        assert verdict == "failed"
