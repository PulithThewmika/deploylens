from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .alert import Alert
    from .health_assessment import HealthAssessment
    from .service import Service


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    commit_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    build_status: Mapped[str | None] = mapped_column(String)
    build_duration_s: Mapped[float | None] = mapped_column(Float)
    sync_status: Mapped[str | None] = mapped_column(String)
    workflow_run_id: Mapped[int | None] = mapped_column(BigInteger)
    argocd_revision: Mapped[str | None] = mapped_column(Text)
    image_tag: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(nullable=False, server_default="now()")
    finished_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default="now()")

    service: Mapped[Service] = relationship(back_populates="deployments")
    health_assessment: Mapped[HealthAssessment | None] = relationship(back_populates="deployment", uselist=False)
    alerts: Mapped[list[Alert]] = relationship(back_populates="deployment")
