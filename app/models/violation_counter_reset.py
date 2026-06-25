from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ViolationCounterReset(Base):
    __tablename__ = "violation_counter_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reset_by_admin_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reset_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
