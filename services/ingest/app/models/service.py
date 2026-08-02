from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .alert import Alert
    from .deployment import Deployment


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    repo: Mapped[str | None] = mapped_column(Text)
    argocd_app: Mapped[str | None] = mapped_column(Text)
    namespace: Mapped[str] = mapped_column(String, nullable=False, server_default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    deployments: Mapped[list[Deployment]] = relationship(back_populates="service")
    alerts: Mapped[list[Alert]] = relationship(back_populates="service")
