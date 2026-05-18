from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlayerCapitalContributionSnapshot(Base):
    __tablename__ = "player_capital_contribution_snapshots"
    __table_args__ = (
        Index("ix_player_capital_contrib_player_observed", "player_tag", "observed_at"),
        Index("ix_player_capital_contrib_clan_observed", "clan_tag", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    clan_tag: Mapped[str] = mapped_column(String(20), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
