from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CapitalRaidWeekend(Base):
    __tablename__ = "capital_raid_weekends"
    __table_args__ = (UniqueConstraint("clan_tag", "raid_season_id", name="uq_capital_raid_weekend"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    clan_tag: Mapped[str] = mapped_column(String(20), index=True)
    raid_season_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_loot: Mapped[int] = mapped_column(Integer, default=0)
    total_attacks: Mapped[int] = mapped_column(Integer, default=0)
    enemy_districts_destroyed: Mapped[int] = mapped_column(Integer, default=0)
    offensive_reward: Mapped[int] = mapped_column(Integer, default=0)
    defensive_reward: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    participants = relationship("CapitalRaidParticipant", back_populates="weekend", cascade="all, delete-orphan")


class CapitalRaidParticipant(Base):
    __tablename__ = "capital_raid_participants"
    __table_args__ = (UniqueConstraint("weekend_id", "player_tag", name="uq_capital_raid_participant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    weekend_id: Mapped[int] = mapped_column(ForeignKey("capital_raid_weekends.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("player_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    player_name: Mapped[str] = mapped_column(String(100))
    attacks: Mapped[int] = mapped_column(Integer, default=0)
    attack_limit: Mapped[int] = mapped_column(Integer, default=0)
    bonus_attacks: Mapped[int] = mapped_column(Integer, default=0)
    capital_resources_looted: Mapped[int] = mapped_column(Integer, default=0)
    districts_destroyed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clan_capital_contributions_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)

    weekend = relationship("CapitalRaidWeekend", back_populates="participants")
