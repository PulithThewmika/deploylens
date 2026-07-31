import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.deployment import Deployment
from ..models.service import Service

logger = logging.getLogger("deploylens.correlation")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def extract_image_tag(head_sha: str | None) -> str | None:
    if head_sha and len(head_sha) >= 7:
        return head_sha[:7]
    return head_sha


@dataclass
class CorrelationResult:
    deployment: Deployment
    service_id: int
    method: str  # "commit_sha", "image_tag", "orphan", "new"
    is_new: bool


async def resolve_service(
    session: AsyncSession,
    *,
    repo: str | None = None,
    argocd_app: str | None = None,
) -> int:
    if repo:
        result = await session.execute(
            select(Service).where(Service.repo == repo)
        )
        service = result.scalar_one_or_none()
        if service is not None:
            return service.id

    if argocd_app:
        result = await session.execute(
            select(Service).where(Service.argocd_app == argocd_app)
        )
        service = result.scalar_one_or_none()
        if service is not None:
            return service.id

    name = (
        repo.split("/")[-1] if repo
        else argocd_app if argocd_app
        else "unknown"
    )

    result = await session.execute(
        select(Service).where(Service.name == name)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if repo and not existing.repo:
            existing.repo = repo
            logger.info("Linked repo '%s' to existing service '%s' (id=%d)", repo, name, existing.id)
        if argocd_app and not existing.argocd_app:
            existing.argocd_app = argocd_app
            logger.info("Linked ArgoCD app '%s' to existing service '%s' (id=%d)", argocd_app, name, existing.id)
        await session.flush()
        return existing.id

    service = Service(name=name, repo=repo, argocd_app=argocd_app)
    session.add(service)
    await session.flush()
    logger.info(
        "Auto-registered service '%s' (id=%d, repo=%s, argocd_app=%s)",
        name, service.id, repo, argocd_app,
    )
    return service.id


async def find_matching_deployment(
    session: AsyncSession,
    service_id: int,
    *,
    commit_sha: str | None = None,
    image_tag: str | None = None,
) -> tuple[Deployment | None, str]:
    if commit_sha:
        result = await session.execute(
            select(Deployment)
            .where(Deployment.service_id == service_id, Deployment.commit_sha == commit_sha)
            .order_by(Deployment.created_at.desc())
            .limit(1)
        )
        deployment = result.scalar_one_or_none()
        if deployment is not None:
            logger.info(
                "Correlated via commit_sha: deployment_id=%d service_id=%d sha=%s",
                deployment.id, service_id, commit_sha,
            )
            return deployment, "commit_sha"

    if image_tag:
        short_tag = image_tag[:7] if len(image_tag) >= 7 else image_tag
        result = await session.execute(
            select(Deployment)
            .where(Deployment.service_id == service_id, Deployment.image_tag == short_tag)
            .order_by(Deployment.created_at.desc())
            .limit(1)
        )
        deployment = result.scalar_one_or_none()
        if deployment is not None:
            logger.info(
                "Correlated via image_tag fallback: deployment_id=%d service_id=%d tag=%s",
                deployment.id, service_id, short_tag,
            )
            return deployment, "image_tag"

    logger.info(
        "No matching deployment found: service_id=%d sha=%s tag=%s",
        service_id, commit_sha, image_tag,
    )
    return None, "none"
