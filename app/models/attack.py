from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Attack(Base):
    __tablename__ = "attacks"
    __table_args__ = (UniqueConstraint("war_id", "attacker_tag", "defender_tag", "attack_order", name="uq_attack_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    war_id: Mapped[int] = mapped_column(ForeignKey("wars.id", ondelete="CASCADE"), index=True)
    attacker_player_id: Mapped[int | None] = mapped_column(ForeignKey("player_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    attacker_tag: Mapped[str] = mapped_column(String(20), index=True)
    attacker_name: Mapped[str] = mapped_column(String(100))
    attacker_position: Mapped[int] = mapped_column(Integer)
    attacker_town_hall: Mapped[int] = mapped_column(Integer)
    defender_tag: Mapped[str] = mapped_column(String(20))
    defender_name: Mapped[str] = mapped_column(String(100))
    defender_position: Mapped[int] = mapped_column(Integer)
    defender_town_hall: Mapped[int] = mapped_column(Integer)
    stars: Mapped[int] = mapped_column(Integer)
    destruction: Mapped[float] = mapped_column(Float)
    attack_order: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    war = relationship("War", back_populates="attacks")
    attacker = relationship("PlayerAccount", back_populates="attacks")
    violation = relationship("Violation", back_populates="attack", cascade="all, delete-orphan", uselist=False)
