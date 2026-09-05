import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import verify_argocd_token
from ..correlation.engine import (
    extract_image_tag,
    extract_image_tag_from_images,
    find_matching_deployment,
    resolve_service,
    utcnow,
)
from ..db import get_session
from ..models.deployment import Deployment
from ..models.pipeline_event import PipelineEvent

logger = logging.getLogger("kubex.webhooks.argocd")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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

    service_id = await resolve_service(session, argocd_app=app_name)

    if not revision:
        revision = operation_state.get("syncResult", {}).get("revision", "")
    if not revision:
        await session.commit()
        logger.info("No revision found in ArgoCD event for app '%s', skipping", app_name)
        return {"status": "ignored", "reason": "no revision in payload"}

    images_str = app_data.get("status", {}).get("summary", {}).get("images")
    image_tag = extract_image_tag_from_images(images_str)
    if image_tag:
        logger.info("Extracted image_tag '%s' from deployed images for app '%s'", image_tag, app_name)
    else:
        image_tag = extract_image_tag(revision)
        logger.info("No images in payload for app '%s', falling back to revision-derived tag '%s'", app_name, image_tag)
    existing, correlation_method = await find_matching_deployment(
        session, service_id, commit_sha=revision, image_tag=image_tag,
    )

    if existing:
        # A prior ArgoCD event for this same revision may have already fired
        # before the real deployment could be identified (e.g. on-sync-running
        # arriving before the GitHub workflow_run completes), creating an
        # orphan row that claimed (argocd_revision, service_id). Now that a
        # later event has correlated this revision to the real deployment
        # via commit_sha/image_tag, that orphan is a stale duplicate of the
        # same physical deployment — remove it so the merge below doesn't
        # collide with the unique index on (argocd_revision, service_id).
        stale_orphan = (
            await session.execute(
                select(Deployment).where(
                    Deployment.service_id == service_id,
                    Deployment.argocd_revision == revision,
                    Deployment.id != existing.id,
                )
            )
        ).scalar_one_or_none()
        if stale_orphan is not None:
            if stale_orphan.status == "assessed":
                # The orphan already has a health assessment (and possibly
                # an alert) attached — deleting it would cascade-delete that
                # real data. This means it sat unmerged long enough for the
                # agent to score it (ArgoCD stuck between on-sync-running
                # and on-sync-succeeded for a full OBSERVATION_WINDOW),
                # unusual enough that we bail out here rather than either
                # losing that history or crashing on the unique-index
                # collision the merge below would otherwise hit.
                await session.commit()
                logger.warning(
                    "Stale orphan deployment_id=%d (revision=%s) already assessed — "
                    "skipping merge into deployment_id=%d to avoid losing its health "
                    "assessment; needs manual reconciliation",
                    stale_orphan.id, revision, existing.id,
                )
                return {
                    "status": "ignored",
                    "reason": f"revision {revision} already assessed on a different deployment "
                              f"(id={stale_orphan.id}); manual reconciliation required",
                }
            logger.info(
                "Reconciling stale orphan deployment_id=%d (revision=%s) into deployment_id=%d",
                stale_orphan.id, revision, existing.id,
            )
            await session.delete(stale_orphan)

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
            image_tag=image_tag,
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
            image_tag=image_tag,
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
            image_tag=image_tag,
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
