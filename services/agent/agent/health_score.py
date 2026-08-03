"""Health score computation — doc 05 formula (exact).

Penalties (each clamped 0-1):
  error_rate:   clamp((post - base) / 0.05, 0, 1)
  latency_p99:  clamp((post/base - 1.2) / 1.8, 0, 1)
  restarts:     clamp((post - base) / 3.0, 0, 1)

Weights: error_rate=45, latency_p99=30, restarts=25
Score:   clamp(100 - sum(weight * penalty), 0, 100), rounded to int
Verdict: >=80 healthy, 50-79 degraded, <50 failed

Guard rail: if request volume < 0.1 rps in both windows, skip
error/latency penalties and note in details JSONB.

Populated in E6-T3 (#32).
"""

from __future__ import annotations


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min_val and max_val."""
    # Placeholder — implemented in E6-T3
    raise NotImplementedError("clamp not yet implemented (E6-T3)")


def penalty(base: float | None, post: float | None, kind: str) -> float:
    """Compute 0-1 penalty for a single metric per doc 05."""
    # Placeholder — implemented in E6-T3
    raise NotImplementedError("penalty not yet implemented (E6-T3)")


def compute_health_score(metrics: dict) -> tuple[int, str, dict]:
    """Compute health score from baseline and observation metrics.

    Returns (score, verdict, details).
    Implemented in E6-T3.
    """
    raise NotImplementedError("compute_health_score not yet implemented (E6-T3)")
