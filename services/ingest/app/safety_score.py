"""Pre-deploy safety score: rule-based (not ML) risk prediction computed
when a GitHub Actions workflow_run "requested" event arrives.

Weighted factors (max 100, per doc 05):
  +25 service change-failure-rate (30d) > 15%
  +20 files_changed > 30 (from the GitHub commit API)
  +15 Friday or weekend, +10 outside 08:00-18:00 (server local time)
  +15 cluster CPU > 75% or memory > 80%
  +15 last deployment of this service was degraded/failed
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models.service import Service
from .promql import fetch_cluster_utilization

logger = logging.getLogger("deploylens.safety_score")

GITHUB_API_TOKEN = os.environ.get("GITHUB_API_TOKEN", "")
GITHUB_API_URL = "https://api.github.com"

CFR_THRESHOLD = 0.15
FILES_CHANGED_THRESHOLD = 30
CLUSTER_CPU_THRESHOLD_PCT = 75.0
CLUSTER_MEM_THRESHOLD_PCT = 80.0


async def _query_cfr_30d(session: AsyncSession, service_name: str) -> float | None:
    result = await session.execute(
        text("""
            SELECT ROUND(
                COUNT(*) FILTER (WHERE is_failure)::numeric
                / NULLIF(COUNT(*), 0),
                4
            )
            FROM dora_change_failure_rate
            WHERE started_at >= now() - 30 * interval '1 day'
            AND service_name = :service
        """),
        {"service": service_name},
    )
    value = result.scalar_one_or_none()
    return float(value) if value is not None else None


async def _query_last_verdict(session: AsyncSession, service_id: int) -> str | None:
    result = await session.execute(
        text("""
            SELECT ha.verdict
            FROM deployments d
            JOIN health_assessments ha ON ha.deployment_id = d.id
            WHERE d.service_id = :service_id
            ORDER BY d.started_at DESC
            LIMIT 1
        """),
        {"service_id": service_id},
    )
    return result.scalar_one_or_none()


async def _fetch_files_changed(repo_full_name: str, commit_sha: str) -> int | None:
    """Number of files changed in a commit, via GitHub's commit API.

    Returns None (never raises) if no token is configured or the API call
    fails — the files_changed factor simply contributes 0 in that case,
    same as any other unavailable signal.
    """
    if not GITHUB_API_TOKEN or not repo_full_name or not commit_sha:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{GITHUB_API_URL}/repos/{repo_full_name}/commits/{commit_sha}",
                headers={
                    "Authorization": f"Bearer {GITHUB_API_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
            )
            resp.raise_for_status()
            files = resp.json().get("files", [])
            return len(files)
    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.warning("Failed to fetch files_changed for %s@%s: %s", repo_full_name, commit_sha, e)
        return None


def _day_and_time_factors(now: datetime) -> tuple[dict, dict]:
    is_friday_or_weekend = now.weekday() >= 4  # Mon=0 ... Fri=4, Sat=5, Sun=6
    is_outside_hours = not (8 <= now.hour < 18)
    day_factor = {"value": now.strftime("%A"), "points": 15 if is_friday_or_weekend else 0}
    time_factor = {"value": now.strftime("%H:%M"), "points": 10 if is_outside_hours else 0}
    return day_factor, time_factor


async def compute_safety_score(
    session: AsyncSession,
    service_id: int,
    commit_sha: str,
    payload: dict,
) -> tuple[int, dict]:
    """Compute a 0-100 pre-deploy risk score with a breakdown of factors.

    `payload` is the raw GitHub workflow_run webhook payload (used here for
    `repository.full_name`).
    """
    service = (
        await session.execute(select(Service).where(Service.id == service_id))
    ).scalar_one_or_none()
    service_name = service.name if service else None
    repo_full_name = payload.get("repository", {}).get("full_name", "")

    score = 0
    factors: dict = {}

    cfr = await _query_cfr_30d(session, service_name) if service_name else None
    cfr_points = 25 if (cfr is not None and cfr > CFR_THRESHOLD) else 0
    score += cfr_points
    factors["cfr_30d"] = {"value": cfr, "threshold": CFR_THRESHOLD, "points": cfr_points}

    # This is computed synchronously in the webhook request path (per spec:
    # "on workflow_run.requested"), not in the agent's async loop like health
    # scoring — so the two independent external calls (GitHub API, Prometheus)
    # run concurrently rather than serially, to stay well under GitHub's
    # webhook delivery timeout even if one of them is slow or unreachable.
    files_changed, cluster = await asyncio.gather(
        _fetch_files_changed(repo_full_name, commit_sha),
        fetch_cluster_utilization(datetime.now()),
    )
    files_points = 20 if (files_changed is not None and files_changed > FILES_CHANGED_THRESHOLD) else 0
    score += files_points
    factors["files_changed"] = {"value": files_changed, "threshold": FILES_CHANGED_THRESHOLD, "points": files_points}

    day_factor, time_factor = _day_and_time_factors(datetime.now())
    score += day_factor["points"] + time_factor["points"]
    factors["day_of_week"] = day_factor
    factors["time_of_day"] = time_factor

    cpu_pct, mem_pct = cluster.get("cpu_pct"), cluster.get("mem_pct")
    cluster_overloaded = (
        (cpu_pct is not None and cpu_pct > CLUSTER_CPU_THRESHOLD_PCT)
        or (mem_pct is not None and mem_pct > CLUSTER_MEM_THRESHOLD_PCT)
    )
    cluster_points = 15 if cluster_overloaded else 0
    score += cluster_points
    factors["cluster_utilization"] = {
        "cpu_pct": cpu_pct, "mem_pct": mem_pct,
        "cpu_threshold_pct": CLUSTER_CPU_THRESHOLD_PCT, "mem_threshold_pct": CLUSTER_MEM_THRESHOLD_PCT,
        "points": cluster_points,
    }

    last_verdict = await _query_last_verdict(session, service_id)
    last_deploy_bad = last_verdict in ("degraded", "failed")
    last_deploy_points = 15 if last_deploy_bad else 0
    score += last_deploy_points
    factors["last_deploy_verdict"] = {"value": last_verdict, "points": last_deploy_points}

    score = max(0, min(100, score))
    logger.info(
        "Safety score for service_id=%d commit=%s: %d/100 (factors: %s)",
        service_id, commit_sha[:7] if commit_sha else "unknown", score,
        {k: v["points"] for k, v in factors.items()},
    )
    return score, factors
