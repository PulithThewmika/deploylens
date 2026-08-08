import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("deploylens.api")

from ..auth import verify_alertmanager_token
from ..db import get_session
from ..schemas.responses import (
    ServiceWithStatusResponse,
    LatestDeployInfo,
    HealthSummary,
    DORAMetricsResponse,
    AlertResponse,
    DeploymentListItem,
    DeploymentDetailWithTimelineResponse,
    DeploymentDetailResponse,
    HealthAssessmentResponse,
    ServiceResponse,
    TimelineStage,
    HealthEvidenceItem,
    HealthDetailResponse,
    CompareResponse,
    CompareMetric,
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


@router.get("/deployments", response_model=list[DeploymentListItem])
async def list_deployments(
    service: str | None = Query(None, description="Filter by service name"),
    status: str | None = Query(None, description="Filter by deployment status"),
    limit: int = Query(10, ge=1, le=50, description="Max results (default 10, max 50)"),
    session: AsyncSession = Depends(get_session),
):
    """List deployments with optional service/status filters."""
    conditions = []
    params: dict = {"limit": limit}

    if service:
        conditions.append("s.name = :service")
        params["service"] = service

    if status:
        conditions.append("d.status = :status")
        params["status"] = status

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    result = await session.execute(
        text(f"""
            SELECT d.id, d.service_id, s.name AS service_name,
                   d.commit_sha, d.branch, d.author, d.status,
                   d.image_tag, d.started_at, d.finished_at,
                   ha.score AS health_score, ha.verdict AS health_verdict
            FROM deployments d
            JOIN services s ON s.id = d.service_id
            LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
            {where_clause}
            ORDER BY d.started_at DESC
            LIMIT :limit
        """),
        params,
    )
    rows = result.fetchall()

    return [
        DeploymentListItem(
            id=row.id,
            service_id=row.service_id,
            service_name=row.service_name,
            commit_sha=row.commit_sha,
            branch=row.branch,
            author=row.author,
            status=row.status,
            image_tag=row.image_tag,
            started_at=row.started_at,
            finished_at=row.finished_at,
            health=HealthSummary(score=row.health_score, verdict=row.health_verdict)
            if row.health_score is not None else None,
        )
        for row in rows
    ]


def _build_timeline(row) -> list[TimelineStage]:
    """Construct deployment timeline from stage timestamps."""
    stages = []

    if row.commit_at:
        stages.append(TimelineStage(stage="commit", at=row.commit_at, status="completed"))

    if row.started_at:
        build_duration = None
        if row.build_duration_s is not None:
            build_duration = row.build_duration_s
        build_status = row.build_status or ("completed" if row.status not in ("pending", "building", "build_failed") else row.status)
        stages.append(TimelineStage(
            stage="build", at=row.started_at, status=build_status,
            duration_s=build_duration,
        ))

    if row.argocd_revision:
        sync_status = row.sync_status or ("completed" if row.status in ("deployed", "assessed") else "in_progress")
        stages.append(TimelineStage(stage="sync", at=None, status=sync_status))

    if row.finished_at and row.status in ("deployed", "assessed"):
        stages.append(TimelineStage(stage="deploy", at=row.finished_at, status="completed"))

    if row.assessed_at:
        stages.append(TimelineStage(stage="assess", at=row.assessed_at, status="completed"))

    return stages


def _build_health_evidence(row) -> list[HealthEvidenceItem]:
    """Build evidence array from health assessment columns."""
    evidence = []

    if row.error_rate_base is not None or row.error_rate_post is not None:
        change = None
        if row.error_rate_base is not None and row.error_rate_post is not None and row.error_rate_base > 0:
            change = round((row.error_rate_post - row.error_rate_base) / row.error_rate_base * 100, 1)
        evidence.append(HealthEvidenceItem(
            metric="error_rate", baseline=row.error_rate_base,
            post=row.error_rate_post, change_pct=change,
        ))

    if row.latency_p99_base_ms is not None or row.latency_p99_post_ms is not None:
        change = None
        if row.latency_p99_base_ms is not None and row.latency_p99_post_ms is not None and row.latency_p99_base_ms > 0:
            change = round((row.latency_p99_post_ms - row.latency_p99_base_ms) / row.latency_p99_base_ms * 100, 1)
        evidence.append(HealthEvidenceItem(
            metric="latency_p99", baseline=row.latency_p99_base_ms,
            post=row.latency_p99_post_ms, change_pct=change,
        ))

    if row.restarts_base is not None or row.restarts_post is not None:
        change = None
        if row.restarts_base is not None and row.restarts_post is not None and row.restarts_base > 0:
            change = round((row.restarts_post - row.restarts_base) / row.restarts_base * 100, 1)
        evidence.append(HealthEvidenceItem(
            metric="restarts", baseline=row.restarts_base,
            post=row.restarts_post, change_pct=change,
        ))

    return evidence


@router.get("/deployments/{deploy_id}", response_model=DeploymentDetailWithTimelineResponse)
async def get_deployment_detail(
    deploy_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get full deployment detail with timeline and health evidence."""
    result = await session.execute(
        text("""
            SELECT d.id, d.service_id, d.commit_sha, d.branch, d.author,
                   d.status, d.image_tag, d.started_at, d.finished_at,
                   d.commit_at, d.build_status, d.build_duration_s,
                   d.sync_status, d.workflow_run_id, d.argocd_revision,
                   d.created_at,
                   s.id AS s_id, s.name AS s_name, s.repo AS s_repo,
                   s.argocd_app AS s_argocd_app, s.namespace AS s_namespace,
                   s.created_at AS s_created_at,
                   ha.id AS ha_id, ha.score, ha.verdict,
                   ha.error_rate_base, ha.error_rate_post,
                   ha.latency_p99_base_ms, ha.latency_p99_post_ms,
                   ha.restarts_base, ha.restarts_post,
                   ha.details, ha.assessed_at
            FROM deployments d
            JOIN services s ON s.id = d.service_id
            LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
            WHERE d.id = :deploy_id
        """),
        {"deploy_id": deploy_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    health_assessment = None
    if row.ha_id is not None:
        health_assessment = HealthAssessmentResponse(
            id=row.ha_id,
            deployment_id=row.id,
            score=row.score,
            verdict=row.verdict,
            error_rate_base=row.error_rate_base,
            error_rate_post=row.error_rate_post,
            latency_p99_base_ms=row.latency_p99_base_ms,
            latency_p99_post_ms=row.latency_p99_post_ms,
            restarts_base=row.restarts_base,
            restarts_post=row.restarts_post,
            details=row.details,
            assessed_at=row.assessed_at,
        )

    service = ServiceResponse(
        id=row.s_id,
        name=row.s_name,
        repo=row.s_repo,
        argocd_app=row.s_argocd_app,
        namespace=row.s_namespace,
        created_at=row.s_created_at,
    )

    return DeploymentDetailWithTimelineResponse(
        id=row.id,
        service_id=row.service_id,
        commit_sha=row.commit_sha,
        branch=row.branch,
        author=row.author,
        status=row.status,
        image_tag=row.image_tag,
        started_at=row.started_at,
        finished_at=row.finished_at,
        commit_at=row.commit_at,
        build_status=row.build_status,
        build_duration_s=row.build_duration_s,
        sync_status=row.sync_status,
        workflow_run_id=row.workflow_run_id,
        argocd_revision=row.argocd_revision,
        created_at=row.created_at,
        health_assessment=health_assessment,
        service=service,
        timeline=_build_timeline(row),
        health_evidence=_build_health_evidence(row),
    )


@router.get("/deployments/{deploy_id}/health", response_model=HealthDetailResponse)
async def get_deployment_health(
    deploy_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get health assessment for a deployment with evidence array."""
    result = await session.execute(
        text("""
            SELECT d.id AS deploy_id, d.status,
                   ha.score, ha.verdict, ha.assessed_at,
                   ha.error_rate_base, ha.error_rate_post,
                   ha.latency_p99_base_ms, ha.latency_p99_post_ms,
                   ha.restarts_base, ha.restarts_post
            FROM deployments d
            LEFT JOIN health_assessments ha ON ha.deployment_id = d.id
            WHERE d.id = :deploy_id
        """),
        {"deploy_id": deploy_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if row.score is None:
        return HealthDetailResponse(
            deployment_id=deploy_id,
            status="pending",
        )

    return HealthDetailResponse(
        deployment_id=deploy_id,
        status="assessed",
        score=row.score,
        verdict=row.verdict,
        assessed_at=row.assessed_at,
        evidence=_build_health_evidence(row),
    )


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

    # Deploy frequency: deployments per day in period (dora_deploy_frequency view)
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

    # Lead time: average seconds from commit to deploy (dora_lead_time view)
    lt_result = await session.execute(
        text(f"""
            SELECT AVG(lead_time_seconds)
            FROM dora_lead_time
            WHERE finished_at >= now() - :days * interval '1 day'
            {svc_filter}
        """),
        params,
    )
    lead_time_avg = lt_result.scalar_one_or_none()

    # Change failure rate (dora_change_failure_rate view)
    cfr_result = await session.execute(
        text(f"""
            SELECT ROUND(
                COUNT(*) FILTER (WHERE is_failure)::numeric
                / NULLIF(COUNT(*), 0),
                4
            )
            FROM dora_change_failure_rate
            WHERE started_at >= now() - :days * interval '1 day'
            {svc_filter}
        """),
        params,
    )
    cfr = cfr_result.scalar_one_or_none()
    cfr_float = float(cfr) if cfr is not None else None

    # MTTR: average resolved alert duration (dora_mttr view)
    mttr_result = await session.execute(
        text(f"""
            SELECT AVG(mttr_seconds)
            FROM dora_mttr
            WHERE fired_at >= now() - :days * interval '1 day'
            {svc_filter}
        """),
        params,
    )
    mttr = mttr_result.scalar_one_or_none()

    return DORAMetricsResponse(
        deploy_frequency_per_day=freq,
        lead_time_avg_s=lead_time_avg,
        change_failure_rate=cfr_float,
        mttr_s=mttr,
        period=period,
        service=service,
    )


@router.get("/alerts", response_model=list[AlertResponse])
async def list_alerts(
    active: bool | None = Query(None, description="Filter active alerts (resolved_at IS NULL)"),
    service: str | None = Query(None, description="Filter by service name"),
    session: AsyncSession = Depends(get_session),
):
    """List alerts with optional active/service filters."""
    conditions = []
    params: dict = {}

    if active is True:
        conditions.append("a.resolved_at IS NULL")
    elif active is False:
        conditions.append("a.resolved_at IS NOT NULL")

    if service:
        conditions.append("s.name = :service")
        params["service"] = service

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    result = await session.execute(
        text(f"""
            SELECT a.id, a.deployment_id, a.service_id, a.severity,
                   a.title, a.description, a.fired_at, a.resolved_at,
                   a.alertmanager_id
            FROM alerts a
            JOIN services s ON s.id = a.service_id
            {where_clause}
            ORDER BY a.fired_at DESC
        """),
        params,
    )
    rows = result.fetchall()

    return [
        AlertResponse(
            id=row.id,
            deployment_id=row.deployment_id,
            service_id=row.service_id,
            severity=row.severity,
            title=row.title,
            description=row.description,
            fired_at=row.fired_at,
            resolved_at=row.resolved_at,
            alertmanager_id=row.alertmanager_id,
        )
        for row in rows
    ]


@router.get("/compare", response_model=CompareResponse)
async def compare_deployments(
    a: int = Query(..., description="First deployment ID"),
    b: int = Query(..., description="Second deployment ID"),
    session: AsyncSession = Depends(get_session),
):
    """Compare two deployments side-by-side with live PromQL metrics."""
    from ..promql import fetch_metrics_at, OBSERVATION_WINDOW

    result = await session.execute(
        text("""
            SELECT d.id, d.service_id, d.finished_at,
                   s.name AS service_name, s.namespace
            FROM deployments d
            JOIN services s ON s.id = d.service_id
            WHERE d.id IN (:a, :b)
        """),
        {"a": a, "b": b},
    )
    rows = {row.id: row for row in result.fetchall()}

    if a not in rows:
        raise HTTPException(status_code=404, detail=f"Deployment {a} not found")
    if b not in rows:
        raise HTTPException(status_code=404, detail=f"Deployment {b} not found")

    row_a, row_b = rows[a], rows[b]

    if row_a.service_id != row_b.service_id:
        raise HTTPException(
            status_code=400,
            detail="Both deployments must belong to the same service",
        )

    if not row_a.finished_at or not row_b.finished_at:
        raise HTTPException(
            status_code=400,
            detail="Both deployments must have finished_at timestamps",
        )

    service_name = row_a.service_name
    namespace = row_a.namespace

    metrics_a = await fetch_metrics_at(
        service_name, namespace, OBSERVATION_WINDOW, row_a.finished_at,
    )
    metrics_b = await fetch_metrics_at(
        service_name, namespace, OBSERVATION_WINDOW, row_b.finished_at,
    )

    compare_metrics = []
    for metric_key, label in [
        ("error_rate", "error_rate"),
        ("latency_p99_ms", "latency_p99"),
        ("restarts", "restarts"),
    ]:
        val_a = metrics_a.get(metric_key)
        val_b = metrics_b.get(metric_key)
        change = None
        if val_a is not None and val_b is not None and val_a > 0:
            change = round((val_b - val_a) / val_a * 100, 1)
        compare_metrics.append(CompareMetric(
            metric=label, deploy_a=val_a, deploy_b=val_b, change_pct=change,
        ))

    return CompareResponse(
        deploy_a_id=a,
        deploy_b_id=b,
        service=service_name,
        metrics=compare_metrics,
    )


@router.post("/alerts/inbound", dependencies=[Depends(verify_alertmanager_token)])
async def alerts_inbound(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Receive Alertmanager webhook notifications.

    For resolved alerts, updates alerts.resolved_at matching on labels
    (service, deploy_id). Idempotent — duplicate resolutions are no-ops.
    """
    payload = await request.json()

    alerts = payload.get("alerts", [])
    resolved_count = 0

    for alert in alerts:
        if alert.get("status") != "resolved":
            continue

        labels = alert.get("labels", {})
        deploy_id = labels.get("deploy_id")
        service = labels.get("service")

        if not deploy_id or not service:
            logger.warning(
                "Resolved alert missing deploy_id or service label, skipping"
            )
            continue

        try:
            deploy_id_int = int(deploy_id)
        except (TypeError, ValueError):
            logger.warning(
                "Resolved alert has non-numeric deploy_id label %r, skipping",
                deploy_id,
            )
            continue

        ends_at_raw = alert.get("endsAt")
        ends_at = None
        if ends_at_raw:
            try:
                ends_at = datetime.fromisoformat(ends_at_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                logger.warning(
                    "Could not parse endsAt=%r for deploy %s, falling back to now()",
                    ends_at_raw, deploy_id,
                )

        result = await session.execute(
            text("""
                UPDATE alerts
                SET resolved_at = COALESCE(resolved_at, :ends_at, now())
                WHERE deployment_id = :deploy_id
                  AND resolved_at IS NULL
                  AND service_id = (
                      SELECT id FROM services WHERE name = :service LIMIT 1
                  )
            """),
            {"deploy_id": deploy_id_int, "service": service, "ends_at": ends_at},
        )

        if result.rowcount > 0:
            resolved_count += result.rowcount
            logger.info(
                "Resolved %d alert(s) for deploy %s service %s",
                result.rowcount, deploy_id, service,
            )
        else:
            logger.info(
                "No unresolved alert found for deploy %s service %s (already resolved or not found)",
                deploy_id, service,
            )

    await session.commit()
    return {"status": "ok", "resolved": resolved_count}
