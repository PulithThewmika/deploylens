import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import verify_argocd_token
from ..db import get_session
from ..models.deployment import Deployment
from ..models.pipeline_event import PipelineEvent
from ..models.service import Service

logger = logging.getLogger("deploylens.webhooks.argocd")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_service_by_app(session: AsyncSession, app_name: str) -> int:
    result = await session.execute(
        select(Service).where(Service.argocd_app == app_name)
    )
    service = result.scalar_one_or_none()
    if service is not None:
        return service.id

    result = await session.execute(
        select(Service).where(Service.name == app_name)
    )
    service = result.scalar_one_or_none()
    if service is not None:
        service.argocd_app = app_name
        await session.flush()
        logger.info("Linked ArgoCD app '%s' to existing service (id=%d)", app_name, service.id)
        return service.id

    service = Service(name=app_name, argocd_app=app_name)
    session.add(service)
    await session.flush()
    logger.info("Auto-registered service '%s' from ArgoCD app (id=%d)", app_name, service.id)
    return service.id


async def find_deployment_by_sha(
    session: AsyncSession, service_id: int, revision: str
) -> Deployment | None:
    result = await session.execute(
        select(Deployment)
        .where(Deployment.service_id == service_id, Deployment.commit_sha == revision)
        .order_by(Deployment.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_deployment_by_image_tag(
    session: AsyncSession, service_id: int, revision: str
) -> Deployment | None:
    short_rev = revision[:7] if len(revision) >= 7 else revision
    result = await session.execute(
        select(Deployment)
        .where(Deployment.service_id == service_id, Deployment.image_tag == short_rev)
        .order_by(Deployment.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/argocd")
async def argocd_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_argocd_token),
):
    payload = await request.json()

    app_data = payload.get("app", {})
    app_name = app_data.get("metadata", {}).get("name", "")
    sync_status_obj = app_data.get("status", {}).get("sync", {})
    revision = sync_status_obj.get("revision", "")
    operation_state = app_data.get("status", {}).get("operationState", {})
    health_status = app_data.get("status", {}).get("health", {}).get("status", "")
    event_type = payload.get("type", "unknown")

    await session.execute(
        PipelineEvent.__table__.insert().values(
            source="argocd",
            event_type=event_type,
            payload=payload,
        )
    )

    if not app_name:
        await session.commit()
        return {"status": "ignored", "reason": "missing app.metadata.name"}

    service_id = await resolve_service_by_app(session, app_name)

    if not revision:
        revision = operation_state.get("syncResult", {}).get("revision", "")
    if not revision:
        await session.commit()
        logger.info("No revision found in ArgoCD event for app '%s', skipping", app_name)
        return {"status": "ignored", "reason": "no revision in payload"}

    existing = await find_deployment_by_sha(session, service_id, revision)
    correlation_method = "commit_sha"
    if existing is None:
        existing = await find_deployment_by_image_tag(session, service_id, revision)
        correlation_method = "image_tag"

    if event_type == "on-sync-running":
        if existing:
            existing.status = "syncing"
            existing.argocd_revision = revision
            existing.sync_status = "OutOfSync"
            await session.commit()
            logger.info(
                "Deployment syncing (correlated via %s): service_id=%d deployment_id=%d revision=%s",
                correlation_method, service_id, existing.id, revision,
            )
            return {"status": "ok", "deployment_status": "syncing", "correlation": correlation_method}

        stmt = pg_insert(Deployment).values(
            service_id=service_id,
            commit_sha=revision,
            status="syncing",
            sync_status="OutOfSync",
            argocd_revision=revision,
            image_tag=revision[:7] if len(revision) >= 7 else revision,
            started_at=utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["argocd_revision", "service_id"],
            index_where=Deployment.argocd_revision.is_not(None),
            set_={
                "status": "syncing",
                "sync_status": "OutOfSync",
            },
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(
            "Orphan deployment created (syncing): service_id=%d revision=%s app=%s",
            service_id, revision, app_name,
        )
        return {"status": "ok", "deployment_status": "syncing", "correlation": "orphan"}

    elif event_type == "on-sync-succeeded":
        if existing:
            existing.status = "deployed"
            existing.sync_status = "Synced"
            existing.argocd_revision = revision
            existing.finished_at = utcnow()
            await session.commit()
            logger.info(
                "Deployment deployed (correlated via %s): service_id=%d deployment_id=%d revision=%s",
                correlation_method, service_id, existing.id, revision,
            )
            return {"status": "ok", "deployment_status": "deployed", "correlation": correlation_method}

        stmt = pg_insert(Deployment).values(
            service_id=service_id,
            commit_sha=revision,
            status="deployed",
            sync_status="Synced",
            argocd_revision=revision,
            image_tag=revision[:7] if len(revision) >= 7 else revision,
            started_at=utcnow(),
            finished_at=utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["argocd_revision", "service_id"],
            index_where=Deployment.argocd_revision.is_not(None),
            set_={
                "status": "deployed",
                "sync_status": "Synced",
                "finished_at": utcnow(),
            },
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(
            "Orphan deployment created (deployed): service_id=%d revision=%s app=%s",
            service_id, revision, app_name,
        )
        return {"status": "ok", "deployment_status": "deployed", "correlation": "orphan"}

    elif event_type == "on-sync-failed":
        if existing:
            existing.status = "sync_failed"
            existing.sync_status = "Failed"
            existing.argocd_revision = revision
            existing.finished_at = utcnow()
            await session.commit()
            logger.info(
                "Deployment sync_failed (correlated via %s): service_id=%d deployment_id=%d revision=%s",
                correlation_method, service_id, existing.id, revision,
            )
            return {"status": "ok", "deployment_status": "sync_failed", "correlation": correlation_method}

        stmt = pg_insert(Deployment).values(
            service_id=service_id,
            commit_sha=revision,
            status="sync_failed",
            sync_status="Failed",
            argocd_revision=revision,
            image_tag=revision[:7] if len(revision) >= 7 else revision,
            started_at=utcnow(),
            finished_at=utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["argocd_revision", "service_id"],
            index_where=Deployment.argocd_revision.is_not(None),
            set_={
                "status": "sync_failed",
                "sync_status": "Failed",
                "finished_at": utcnow(),
            },
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(
            "Orphan deployment created (sync_failed): service_id=%d revision=%s app=%s",
            service_id, revision, app_name,
        )
        return {"status": "ok", "deployment_status": "sync_failed", "correlation": "orphan"}

    else:
        await session.commit()
        logger.info("Ignoring ArgoCD event type '%s' for app '%s'", event_type, app_name)
        return {"status": "ignored", "reason": f"event type '{event_type}' not handled"}
