import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import verify_github_signature
from ..db import get_session
from ..models.deployment import Deployment
from ..models.pipeline_event import PipelineEvent
from ..models.service import Service

logger = logging.getLogger("deploylens.webhooks.github")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def resolve_service(session: AsyncSession, repo_full_name: str) -> int:
    result = await session.execute(
        select(Service.id).where(Service.repo == repo_full_name)
    )
    service_id = result.scalar_one_or_none()
    if service_id is not None:
        return service_id

    short_name = repo_full_name.split("/")[-1]
    service = Service(name=short_name, repo=repo_full_name)
    session.add(service)
    await session.flush()
    logger.info("Auto-registered service '%s' from repo '%s' (id=%d)", short_name, repo_full_name, service.id)
    return service.id


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def extract_image_tag(workflow_run: dict) -> str | None:
    name = workflow_run.get("name", "")
    head_sha = workflow_run.get("head_sha", "")
    if head_sha:
        return head_sha[:7]
    return None


@router.post("/github")
async def github_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    body = await verify_github_signature(request)
    payload = json.loads(body)

    event_type = request.headers.get("X-GitHub-Event", "unknown")

    await session.execute(
        PipelineEvent.__table__.insert().values(
            source="github_actions",
            event_type=event_type,
            payload=payload,
        )
    )

    if event_type != "workflow_run":
        await session.commit()
        logger.info("Received non-workflow_run event '%s', stored in pipeline_events only", event_type)
        return {"status": "ignored", "reason": f"event type '{event_type}' not handled"}

    action = payload.get("action")
    workflow_run = payload.get("workflow_run", {})
    repo_full_name = payload.get("repository", {}).get("full_name", "")

    if not repo_full_name:
        await session.commit()
        return {"status": "ignored", "reason": "missing repository.full_name"}

    service_id = await resolve_service(session, repo_full_name)
    workflow_run_id = workflow_run.get("id")
    commit_sha = workflow_run.get("head_sha")
    branch = workflow_run.get("head_branch")
    author = workflow_run.get("actor", {}).get("login")
    commit_at = parse_iso_timestamp(
        workflow_run.get("head_commit", {}).get("timestamp")
        if workflow_run.get("head_commit")
        else None
    )
    image_tag = extract_image_tag(workflow_run)

    if action == "requested":
        stmt = pg_insert(Deployment).values(
            service_id=service_id,
            commit_sha=commit_sha,
            branch=branch,
            author=author,
            commit_at=commit_at,
            status="building",
            workflow_run_id=workflow_run_id,
            image_tag=image_tag,
            started_at=utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["workflow_run_id"],
            index_where=Deployment.workflow_run_id.is_not(None),
            set_={
                "commit_sha": stmt.excluded.commit_sha,
                "branch": stmt.excluded.branch,
                "author": stmt.excluded.author,
                "commit_at": stmt.excluded.commit_at,
                "status": case(
                    (Deployment.status.in_(["pending", "building"]), "building"),
                    else_=Deployment.status,
                ),
                "image_tag": stmt.excluded.image_tag,
            },
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(
            "Deployment building: service_id=%d workflow_run_id=%s commit=%s branch=%s",
            service_id, workflow_run_id, commit_sha, branch,
        )
        return {"status": "ok", "deployment_status": "building"}

    elif action == "completed":
        conclusion = workflow_run.get("conclusion")

        run_started_at = parse_iso_timestamp(workflow_run.get("run_started_at"))
        updated_at = parse_iso_timestamp(workflow_run.get("updated_at"))
        build_duration_s = None
        if run_started_at and updated_at:
            build_duration_s = (updated_at - run_started_at).total_seconds()

        if conclusion == "success":
            new_status = "built"
            new_build_status = "success"
        else:
            new_status = "build_failed"
            new_build_status = conclusion or "failure"

        stmt = pg_insert(Deployment).values(
            service_id=service_id,
            commit_sha=commit_sha,
            branch=branch,
            author=author,
            commit_at=commit_at,
            status=new_status,
            build_status=new_build_status,
            build_duration_s=build_duration_s,
            workflow_run_id=workflow_run_id,
            image_tag=image_tag,
            started_at=utcnow(),
            finished_at=utcnow() if conclusion else None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["workflow_run_id"],
            index_where=Deployment.workflow_run_id.is_not(None),
            set_={
                "status": new_status,
                "build_status": new_build_status,
                "build_duration_s": build_duration_s,
                "finished_at": utcnow(),
                "image_tag": stmt.excluded.image_tag,
            },
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(
            "Deployment %s: service_id=%d workflow_run_id=%s conclusion=%s duration=%.1fs",
            new_status, service_id, workflow_run_id, conclusion,
            build_duration_s or 0,
        )
        return {"status": "ok", "deployment_status": new_status}

    else:
        await session.commit()
        logger.info("Ignoring workflow_run action '%s'", action)
        return {"status": "ignored", "reason": f"action '{action}' not handled"}
