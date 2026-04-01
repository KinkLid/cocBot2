from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReturnEvent(Base):
    __tablename__ = "return_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    player_name: Mapped[str] = mapped_column(String(100))
    returned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    was_purged: Mapped[bool] = mapped_column(Boolean, default=False)
