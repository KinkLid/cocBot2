from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TelegramUser(Base):
    __tablename__ = "telegram_users"
    __table_args__ = (Index("ix_telegram_users_telegram_id", "telegram_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    links = relationship("TelegramPlayerLink", back_populates="telegram_user", cascade="all, delete-orphan")
