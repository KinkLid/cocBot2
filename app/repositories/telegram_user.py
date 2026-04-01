from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TelegramPlayerLink, TelegramUser


class TelegramUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, telegram_id: int, username: str | None, now: datetime) -> TelegramUser:
        result = await self.session.execute(select(TelegramUser).where(TelegramUser.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = TelegramUser(telegram_id=telegram_id, username=username, registered_at=now)
            self.session.add(user)
            await self.session.flush()
            return user
        user.username = username
        return user

    async def get_by_telegram_id(self, telegram_id: int) -> TelegramUser | None:
        result = await self.session.execute(select(TelegramUser).where(TelegramUser.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def add_link_if_missing(self, telegram_user_id: int, player_tag: str, now: datetime) -> TelegramPlayerLink:
        result = await self.session.execute(
            select(TelegramPlayerLink).where(
                TelegramPlayerLink.telegram_user_id == telegram_user_id,
                TelegramPlayerLink.player_tag == player_tag,
            )
        )
        link = result.scalar_one_or_none()
        if link is None:
            link = TelegramPlayerLink(telegram_user_id=telegram_user_id, player_tag=player_tag, linked_at=now)
            self.session.add(link)
            await self.session.flush()
        return link

    async def get_links(self, telegram_user_id: int) -> list[TelegramPlayerLink]:
        result = await self.session.execute(
            select(TelegramPlayerLink).where(TelegramPlayerLink.telegram_user_id == telegram_user_id).order_by(TelegramPlayerLink.linked_at)
        )
        return list(result.scalars().all())
