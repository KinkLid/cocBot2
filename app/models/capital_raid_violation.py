from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CapitalRaidViolation(Base):
    __tablename__ = "capital_raid_violations"
    __table_args__ = (
        UniqueConstraint("weekend_id", "player_tag", "code", name="uq_capital_raid_violation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    weekend_id: Mapped[int] = mapped_column(
        ForeignKey("capital_raid_weekends.id", ondelete="CASCADE"), index=True
    )
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    player_name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(64), index=True)
    reason_text: Mapped[str] = mapped_column(String(255))
    attacks: Mapped[int] = mapped_column(Integer)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    weekend = relationship("CapitalRaidWeekend", back_populates="violations")
