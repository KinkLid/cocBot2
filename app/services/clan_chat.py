from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.repositories.settings import ClanSettingsRepository


class ClanChatService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = ClanSettingsRepository(session)

    async def get_chat_url(self) -> str | None:
        settings = await self.repo.get_or_create(self.config.main_clan_tag, self.config.clan_chat_url, self.config.log_level)
        return settings.clan_chat_url

    async def update_chat_url(self, url: str) -> str:
        settings = await self.repo.update_chat_url(self.config.main_clan_tag, url)
        await self.session.commit()
        return settings.clan_chat_url or ""
