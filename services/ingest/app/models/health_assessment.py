from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .deployment import Deployment


class HealthAssessment(Base):
    __tablename__ = "health_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("deployments.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    error_rate_base: Mapped[float | None] = mapped_column(Float)
    error_rate_post: Mapped[float | None] = mapped_column(Float)
    latency_p99_base_ms: Mapped[float | None] = mapped_column(Float)
    latency_p99_post_ms: Mapped[float | None] = mapped_column(Float)
    restarts_base: Mapped[float | None] = mapped_column(Float)
    restarts_post: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict | None] = mapped_column(JSONB)
    assessed_at: Mapped[datetime] = mapped_column(nullable=False, server_default="now()")

    deployment: Mapped[Deployment] = relationship(back_populates="health_assessment")
