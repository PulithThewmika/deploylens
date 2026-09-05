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


def extract_image_tag_from_images(images_str: str | None) -> str | None:
    """Extract the short image tag from ArgoCD's summary.images field.

    ArgoCD renders summary.images as a comma-separated string of image
    references (e.g. "ghcr.io/org/app-frontend:abc1234,ghcr.io/org/app-orders:abc1234").
    All images in a single sync share the same tag, so we take the first one.
    Returns None if the string is empty or contains no parseable tag.
    """
    if not images_str or not images_str.strip():
        return None
    first_image = images_str.split(",")[0].strip().strip("[]")
    if ":" not in first_image:
        return None
    tag = first_image.rsplit(":", 1)[1]
    if not tag or tag == "latest":
        return None
    return tag


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
            select(Service).where(Service.repo == repo).order_by(Service.id)
        )
        services = result.scalars().all()
        if services:
            if len(services) > 1:
                # No unique constraint on repo, so a repo-migration seed
                # update (see V011) racing an auto-registration can leave two
                # rows pointing at the same repo. Prefer the oldest rather
                # than crash the webhook on this - manual reconciliation
                # (merge/delete the newer row) is still needed.
                logger.warning(
                    "Multiple services share repo='%s' (ids=%s) — using oldest (id=%d); "
                    "manual reconciliation needed",
                    repo, [s.id for s in services], services[0].id,
                )
            return services[0].id

    if argocd_app:
        result = await session.execute(
            select(Service).where(Service.argocd_app == argocd_app).order_by(Service.id)
        )
        services = result.scalars().all()
        if services:
            if len(services) > 1:
                logger.warning(
                    "Multiple services share argocd_app='%s' (ids=%s) — using oldest (id=%d); "
                    "manual reconciliation needed",
                    argocd_app, [s.id for s in services], services[0].id,
                )
            return services[0].id

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
