from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .service import Service


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    __table_args__ = (
        # Matches migration V010: source_id/target_id alone aren't unique
        # since one services row can own several components (see
        # services.prom_components) — frontend->orders and orders->payments
        # can share the same source_id/target_id pair in the single-app
        # case, distinguished only by component.
        UniqueConstraint("source_id", "target_id", "dep_type", "source_component", "target_component"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    dep_type: Mapped[str] = mapped_column(String, nullable=False, server_default="calls")
    source_component: Mapped[str | None] = mapped_column(String, nullable=True)
    target_component: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    source: Mapped[Service] = relationship(foreign_keys=[source_id])
    target: Mapped[Service] = relationship(foreign_keys=[target_id])
