from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatModerationMute(Base):
    __tablename__ = "chat_moderation_mutes"
    __table_args__ = (
        UniqueConstraint("chat_id", "telegram_user_id", name="uq_chat_moderation_mute_chat_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(100))
    muted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    muted_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
