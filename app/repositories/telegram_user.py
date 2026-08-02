from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlayerAccount, TelegramPlayerLink, TelegramUser


@dataclass(slots=True)
class TelegramPlayerLinkInfo:
    link_id: int
    telegram_id: int
    username: str | None
    player_tag: str
    player_name: str
    current_in_clan: bool


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

    async def is_registered(self, telegram_id: int) -> bool:
        result = await self.session.execute(
            select(
                exists().where(
                    TelegramUser.telegram_id == telegram_id,
                    TelegramPlayerLink.telegram_user_id == TelegramUser.id,
                )
            )
        )
        return bool(result.scalar())

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

    async def get_linked_telegram_ids(self, player_tag: str) -> list[int]:
        result = await self.session.execute(
            select(TelegramUser.telegram_id)
            .join(TelegramPlayerLink, TelegramPlayerLink.telegram_user_id == TelegramUser.id)
            .where(TelegramPlayerLink.player_tag == player_tag)
            .order_by(TelegramUser.telegram_id)
        )
        return list(result.scalars().all())

    async def get_links(self, telegram_user_id: int) -> list[TelegramPlayerLink]:
        result = await self.session.execute(
            select(TelegramPlayerLink).where(TelegramPlayerLink.telegram_user_id == telegram_user_id).order_by(TelegramPlayerLink.linked_at)
        )
        return list(result.scalars().all())

    async def list_all_links(self) -> list[TelegramPlayerLinkInfo]:
        rows = await self.session.execute(
            select(
                TelegramPlayerLink.id,
                TelegramUser.telegram_id,
                TelegramUser.username,
                TelegramPlayerLink.player_tag,
                PlayerAccount.name,
                PlayerAccount.current_in_clan,
            )
            .join(TelegramUser, TelegramUser.id == TelegramPlayerLink.telegram_user_id)
            .outerjoin(PlayerAccount, PlayerAccount.player_tag == TelegramPlayerLink.player_tag)
            .order_by(PlayerAccount.current_clan_rank.asc().nulls_last(), PlayerAccount.name.asc(), TelegramUser.telegram_id.asc())
        )
        return [
            TelegramPlayerLinkInfo(
                link_id=row[0],
                telegram_id=row[1],
                username=row[2],
                player_tag=row[3],
                player_name=row[4] or row[3],
                current_in_clan=bool(row[5]),
            )
            for row in rows.all()
        ]

    async def remove_link(self, link_id: int) -> bool:
        result = await self.session.execute(
            delete(TelegramPlayerLink).where(TelegramPlayerLink.id == link_id)
        )
        await self.session.flush()
        return bool(result.rowcount)
