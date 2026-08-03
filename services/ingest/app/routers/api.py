from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas.responses import (
    ServiceWithStatusResponse,
    LatestDeployInfo,
    HealthSummary,
    DORAMetricsResponse,
)

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/services", response_model=list[ServiceWithStatusResponse])
async def list_services(session: AsyncSession = Depends(get_session)):
    """List all services with latest deployment, health, and active alert count."""
    result = await session.execute(
        text("""
            SELECT
                s.id, s.name, s.namespace, s.repo, s.argocd_app,
                d.commit_sha     AS latest_commit_sha,
                d.author         AS latest_author,
                d.status         AS latest_status,
                d.finished_at    AS latest_finished_at,
                ha.score         AS health_score,
                ha.verdict       AS health_verdict,
                COALESCE(ac.cnt, 0) AS active_alert_count
            FROM services s
            LEFT JOIN LATERAL (
                SELECT commit_sha, author, status, finished_at
                FROM deployments
                WHERE service_id = s.id
                ORDER BY started_at DESC
                LIMIT 1
            ) d ON true
            LEFT JOIN LATERAL (
                SELECT score, verdict
                FROM health_assessments
                WHERE deployment_id = (
                    SELECT id FROM deployments
                    WHERE service_id = s.id
                    ORDER BY started_at DESC
                    LIMIT 1
                )
            ) ha ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS cnt
                FROM alerts
                WHERE service_id = s.id AND resolved_at IS NULL
            ) ac ON true
            ORDER BY s.name
        """)
    )
    rows = result.fetchall()

    services = []
    for row in rows:
        latest_deploy = None
        if row.latest_status is not None:
            latest_deploy = LatestDeployInfo(
                commit_sha=row.latest_commit_sha,
                author=row.latest_author,
                status=row.latest_status,
                finished_at=row.latest_finished_at,
            )

        health = None
        if row.health_score is not None:
            health = HealthSummary(
                score=row.health_score,
                verdict=row.health_verdict,
            )

        services.append(ServiceWithStatusResponse(
            id=row.id,
            name=row.name,
            namespace=row.namespace,
            repo=row.repo,
            argocd_app=row.argocd_app,
            latest_deploy=latest_deploy,
            health=health,
            active_alert_count=row.active_alert_count,
        ))

    return services


_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/dora", response_model=DORAMetricsResponse)
async def get_dora_metrics(
    service: str | None = Query(None, description="Service name (omit for platform-wide)"),
    period: str = Query("30d", description="Period: 7d, 30d, or 90d"),
    session: AsyncSession = Depends(get_session),
):
    """Return all four DORA metrics for a service and period."""
    days = _PERIOD_DAYS.get(period, 30)
    svc_filter = "AND service_name = :service" if service else ""
    params: dict = {"days": days}
    if service:
        params["service"] = service

    # Deploy frequency: deployments per day in period
    freq_result = await session.execute(
        text(f"""
            SELECT COALESCE(SUM(deploy_count)::float / NULLIF(:days, 0), NULL)
            FROM dora_deploy_frequency
            WHERE deploy_date >= CURRENT_DATE - :days * interval '1 day'
            {svc_filter}
        """),
        params,
    )
    freq = freq_result.scalar_one_or_none()

    # Lead time: median (percentile_cont 0.5)
    lt_result = await session.execute(
        text(f"""
            SELECT percentile_cont(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (d.finished_at - d.commit_at))
            )
            FROM deployments d
            JOIN services s ON s.id = d.service_id
            WHERE d.status IN ('deployed', 'assessed')
              AND d.commit_at IS NOT NULL
              AND d.finished_at IS NOT NULL
              AND d.finished_at >= now() - :days * interval '1 day'
              {"AND s.name = :service" if service else ""}
        """),
        params,
    )
    lead_time_median = lt_result.scalar_one_or_none()

    # Change failure rate
    cfr_result = await session.execute(
        text(f"""
            SELECT
                ROUND(
                    COUNT(*) FILTER (
                        WHERE d.status IN ('build_failed', 'sync_failed')
                           OR ha.verdict IN ('failed', 'degraded')
                    )::numeric / NULLIF(COUNT(*), 0),
                    4
                )
            FROM deployments d
            JOIN services s ON s.id = d.service_id
            LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
            WHERE d.status IN ('deployed', 'assessed', 'build_failed', 'sync_failed')
              AND d.started_at >= now() - :days * interval '1 day'
              {"AND s.name = :service" if service else ""}
        """),
        params,
    )
    cfr = cfr_result.scalar_one_or_none()
    cfr_float = float(cfr) if cfr is not None else None

    # MTTR: average resolved alert duration
    mttr_result = await session.execute(
        text(f"""
            SELECT AVG(EXTRACT(EPOCH FROM (a.resolved_at - a.fired_at)))
            FROM alerts a
            JOIN services s ON s.id = a.service_id
            WHERE a.resolved_at IS NOT NULL
              AND a.fired_at >= now() - :days * interval '1 day'
              {"AND s.name = :service" if service else ""}
        """),
        params,
    )
    mttr = mttr_result.scalar_one_or_none()

    return DORAMetricsResponse(
        deploy_frequency_per_day=freq,
        lead_time_median_s=lead_time_median,
        change_failure_rate=cfr_float,
        mttr_s=mttr,
        period=period,
        service=service,
    )
