from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TelegramPlayerLink(Base):
    __tablename__ = "telegram_player_links"
    __table_args__ = (UniqueConstraint("telegram_user_id", "player_tag", name="uq_telegram_player_link"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id", ondelete="CASCADE"), index=True)
    player_tag: Mapped[str] = mapped_column(String(20), index=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    telegram_user = relationship("TelegramUser", back_populates="links")
