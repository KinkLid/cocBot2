from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ClanSettings(Base):
    __tablename__ = "clan_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    clan_tag: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    clan_chat_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    log_level: Mapped[str] = mapped_column(String(20), default="INFO")
