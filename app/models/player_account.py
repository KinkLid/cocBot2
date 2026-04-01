from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PlayerAccount(Base):
    __tablename__ = "player_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    town_hall: Mapped[int] = mapped_column(Integer, default=1)
    current_clan_tag: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    current_clan_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_clan_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_in_clan: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_seen_in_clan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    first_absent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    memberships = relationship("ClanMembershipHistory", back_populates="player", cascade="all, delete-orphan")
    war_participants = relationship("WarParticipant", back_populates="player", cascade="all, delete-orphan")
    attacks = relationship("Attack", back_populates="attacker", cascade="all, delete-orphan")
