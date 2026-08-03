from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas.responses import (
    ServiceWithStatusResponse,
    LatestDeployInfo,
    HealthSummary,
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
