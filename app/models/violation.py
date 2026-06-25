from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ViolationCode


class Violation(Base):
    __tablename__ = "violations"
    __table_args__ = (
        UniqueConstraint("attack_id", name="uq_violation_attack"),
        Index(
            "uq_violations_cwl_missed_attack_per_war_player",
            "war_id",
            "player_tag",
            unique=True,
            sqlite_where=text("code = 'cwl_missed_attack'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attack_id: Mapped[int | None] = mapped_column(
        ForeignKey("attacks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    war_id: Mapped[int] = mapped_column(ForeignKey("wars.id", ondelete="CASCADE"), index=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    code: Mapped[ViolationCode] = mapped_column(
        Enum(
            ViolationCode,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            validate_strings=True,
            length=32,
        )
    )
    reason_text: Mapped[str] = mapped_column(String(255))
    player_position: Mapped[int] = mapped_column(Integer)
    target_position: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    attack = relationship("Attack", back_populates="violation")
