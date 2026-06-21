from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlayerDonationSnapshot(Base):
    __tablename__ = "player_donation_snapshots"
    __table_args__ = (
        Index("ix_player_donation_snapshots_player_tag", "player_tag"),
        Index("ix_player_donation_snapshots_observed_at", "observed_at"),
        Index("ix_player_donation_snapshots_player_tag_observed_at", "player_tag", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(20), nullable=False)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("player_accounts.id", ondelete="SET NULL"), nullable=True)
    clan_tag: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    donations: Mapped[int] = mapped_column(Integer, default=0)
    donations_received: Mapped[int] = mapped_column(Integer, default=0)
