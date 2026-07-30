from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .service import Service


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "dep_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    dep_type: Mapped[str] = mapped_column(String, nullable=False, server_default="calls")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default="now()")

    source: Mapped[Service] = relationship(foreign_keys=[source_id])
    target: Mapped[Service] = relationship(foreign_keys=[target_id])
