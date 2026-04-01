from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DepartedPlayerArchive(Base):
    __tablename__ = "departed_players_archive"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_tag: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    last_known_name: Mapped[str] = mapped_column(String(100))
    previous_clan_tag: Mapped[str] = mapped_column(String(20))
    departed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    purged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
