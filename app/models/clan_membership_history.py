from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ClanMembershipHistory(Base):
    __tablename__ = "clan_membership_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player_accounts.id", ondelete="CASCADE"), index=True)
    clan_tag: Mapped[str] = mapped_column(String(20), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    player = relationship("PlayerAccount", back_populates="memberships")
