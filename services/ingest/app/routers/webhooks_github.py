import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import verify_github_signature
from ..correlation.engine import (
    extract_image_tag,
    parse_iso_timestamp,
    resolve_service,
    utcnow,
)
from ..db import get_session
from ..models.deployment import Deployment
from ..models.pipeline_event import PipelineEvent
from ..models.safety_score import SafetyScore
from ..safety_score import compute_safety_score

logger = logging.getLogger("deploylens.webhooks.github")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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

    service_id = await resolve_service(session, repo=repo_full_name)
    workflow_run_id = workflow_run.get("id")
    commit_sha = workflow_run.get("head_sha")
    branch = workflow_run.get("head_branch")
    author = workflow_run.get("actor", {}).get("login")
    commit_at = parse_iso_timestamp(
        workflow_run.get("head_commit", {}).get("timestamp")
        if workflow_run.get("head_commit")
        else None
    )
    image_tag = extract_image_tag(commit_sha)

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
        stmt = stmt.returning(Deployment.id)
        deployment_id = (await session.execute(stmt)).scalar_one()

        # Safety scoring is a stretch feature (E14) layered on top of core
        # deployment tracking (M1/M2) — a bug or transient failure in it
        # (a bad CFR query, GitHub/Prometheus being unreachable) must never
        # prevent the deployment itself from being recorded. Isolate it in
        # a savepoint so a failure here rolls back only the safety-score
        # work, not the deployment insert above.
        score = None
        try:
            async with session.begin_nested():
                score, factors = await compute_safety_score(session, service_id, commit_sha, payload)
                safety_stmt = pg_insert(SafetyScore).values(
                    deployment_id=deployment_id,
                    score=score,
                    risk_factors=factors,
                )
                safety_stmt = safety_stmt.on_conflict_do_update(
                    index_elements=["deployment_id"],
                    set_={"score": safety_stmt.excluded.score, "risk_factors": safety_stmt.excluded.risk_factors},
                )
                await session.execute(safety_stmt)
        except Exception as e:
            logger.warning(
                "Safety score computation failed for deployment_id=%d, continuing without it: %s",
                deployment_id, e,
            )
            score = None

        await session.commit()
        logger.info(
            "Deployment building: service_id=%d workflow_run_id=%s commit=%s branch=%s (safety_score=%s)",
            service_id, workflow_run_id, commit_sha, branch, score,
        )
        return {"status": "ok", "deployment_status": "building", "safety_score": score}

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
                # ArgoCD can sync (and fire its own webhook) before this
                # "completed" event arrives, if its poll happens to land
                # while the build is still running. Don't let a late build
                # completion regress a deployment ArgoCD has already
                # advanced past the build phase (e.g. back from "deployed"
                # to "built") — only apply status/finished_at while the
                # deployment is still pre-sync. "build_failed" is included
                # (unlike the "requested" branch's guard) because a manual
                # GitHub Actions re-run reuses the same workflow_run_id and
                # must still be able to transition build_failed -> built.
                "status": case(
                    (Deployment.status.in_(["pending", "building", "build_failed"]), new_status),
                    else_=Deployment.status,
                ),
                "build_status": new_build_status,
                "build_duration_s": build_duration_s,
                "finished_at": case(
                    (Deployment.status.in_(["pending", "building", "build_failed"]), utcnow()),
                    else_=Deployment.finished_at,
                ),
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
