from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import WarState, WarType


class War(Base):
    __tablename__ = "wars"
    __table_args__ = (UniqueConstraint("war_uid", name="uq_war_uid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    war_uid: Mapped[str] = mapped_column(String(255), index=True)
    clan_tag: Mapped[str] = mapped_column(String(20), index=True)
    clan_name: Mapped[str] = mapped_column(String(100))
    opponent_tag: Mapped[str] = mapped_column(String(20))
    opponent_name: Mapped[str] = mapped_column(String(100))
    war_type: Mapped[WarType] = mapped_column(Enum(WarType))
    state: Mapped[WarState] = mapped_column(Enum(WarState), index=True)
    league_group_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    cwl_season: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    round_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_size: Mapped[int] = mapped_column(Integer, default=0)
    is_friendly: Mapped[bool] = mapped_column(Boolean, default=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    preparation_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_payload: Mapped[dict] = mapped_column(JSON)

    participants = relationship("WarParticipant", back_populates="war", cascade="all, delete-orphan")
    attacks = relationship("Attack", back_populates="war", cascade="all, delete-orphan")


class WarParticipant(Base):
    __tablename__ = "war_participants"
    __table_args__ = (UniqueConstraint("war_id", "player_tag", name="uq_war_participant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    war_id: Mapped[int] = mapped_column(ForeignKey("wars.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("player_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(100))
    map_position: Mapped[int] = mapped_column(Integer)
    town_hall: Mapped[int] = mapped_column(Integer)
    is_own_clan: Mapped[bool] = mapped_column(Boolean, default=True)

    war = relationship("War", back_populates="participants")
    player = relationship("PlayerAccount", back_populates="war_participants")
