from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ViolationCode


class Violation(Base):
    __tablename__ = "violations"
    __table_args__ = (UniqueConstraint("attack_id", name="uq_violation_attack"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attack_id: Mapped[int] = mapped_column(ForeignKey("attacks.id", ondelete="CASCADE"), index=True)
    war_id: Mapped[int] = mapped_column(ForeignKey("wars.id", ondelete="CASCADE"), index=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    code: Mapped[ViolationCode] = mapped_column(Enum(ViolationCode))
    reason_text: Mapped[str] = mapped_column(String(255))
    player_position: Mapped[int] = mapped_column(Integer)
    target_position: Mapped[int] = mapped_column(Integer)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    attack = relationship("Attack", back_populates="violation")
