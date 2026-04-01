from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClanSettings


class ClanSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, clan_tag: str, default_chat_url: str | None, log_level: str) -> ClanSettings:
        result = await self.session.execute(select(ClanSettings).where(ClanSettings.clan_tag == clan_tag))
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = ClanSettings(clan_tag=clan_tag, clan_chat_url=default_chat_url, log_level=log_level)
            self.session.add(settings)
            await self.session.flush()
        return settings

    async def update_chat_url(self, clan_tag: str, url: str) -> ClanSettings:
        settings = await self.get_or_create(clan_tag, None, "INFO")
        settings.clan_chat_url = url
        await self.session.flush()
        return settings
