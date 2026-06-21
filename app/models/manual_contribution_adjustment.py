from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ManualContributionAdjustment(Base):
    __tablename__ = "manual_contribution_adjustments"
    __table_args__ = (
        CheckConstraint("points > 0", name="ck_manual_contribution_adjustments_points_positive"),
        Index("ix_manual_contribution_adjustments_player_id", "player_id"),
        Index("ix_manual_contribution_adjustments_clan_tag", "clan_tag"),
        Index("ix_manual_contribution_adjustments_created_at", "created_at"),
        Index("ix_manual_contribution_adjustments_clan_tag_created_at", "clan_tag", "created_at"),
        UniqueConstraint("operation_token", name="uq_manual_contribution_adjustments_operation_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player_accounts.id"), nullable=False)
    clan_tag: Mapped[str] = mapped_column(String(20), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    operation_token: Mapped[str] = mapped_column(String(64), nullable=False)

    player = relationship("PlayerAccount")
