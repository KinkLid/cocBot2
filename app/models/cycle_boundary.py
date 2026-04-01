from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CycleBoundary(Base):
    __tablename__ = "cycle_boundaries"
    __table_args__ = (UniqueConstraint("source_key", name="uq_cycle_boundary_source_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(100), index=True)
    boundary_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str] = mapped_column(String(255))
