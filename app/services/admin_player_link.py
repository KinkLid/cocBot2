from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.models import PlayerAccount
from app.repositories.player_account import PlayerAccountRepository
from app.repositories.telegram_user import TelegramUserRepository
from app.utils.tag import normalize_tag
from app.utils.time import utcnow


@dataclass(slots=True)
class AdminPlayerLinkResult:
    telegram_id: int
    player_tag: str
    player_name: str
    already_linked: bool


class PlayerNotAvailableForLinkError(ValueError):
    pass


class PlayerAlreadyLinkedToAnotherTelegramError(ValueError):
    def __init__(self, owner_telegram_ids: list[int]) -> None:
        self.owner_telegram_ids = owner_telegram_ids
        super().__init__("Игровой аккаунт уже привязан к другому Telegram-пользователю")


class AdminPlayerLinkService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.telegram_users = TelegramUserRepository(session)
        self.players = PlayerAccountRepository(session)

    async def list_active_players(self) -> list[PlayerAccount]:
        return await self.players.active_clan_members(self.config.main_clan_tag)

    async def link_player(self, *, telegram_id: int, player_tag: str) -> AdminPlayerLinkResult:
        if telegram_id <= 0:
            raise ValueError("Telegram ID должен быть положительным числом")
        normalized_tag = normalize_tag(player_tag)
        player = await self.players.get_by_tag(normalized_tag)
        if not (
            player is not None
            and player.current_in_clan is True
            and player.current_clan_tag == self.config.main_clan_tag
        ):
            raise PlayerNotAvailableForLinkError

        linked_ids = await self.telegram_users.get_linked_telegram_ids(normalized_tag)
        foreign_ids = [linked_id for linked_id in linked_ids if linked_id != telegram_id]
        if foreign_ids:
            raise PlayerAlreadyLinkedToAnotherTelegramError(foreign_ids)
        if telegram_id in linked_ids:
            return AdminPlayerLinkResult(
                telegram_id=telegram_id,
                player_tag=normalized_tag,
                player_name=player.name,
                already_linked=True,
            )

        user = await self.telegram_users.get_by_telegram_id(telegram_id)
        if user is None:
            user = await self.telegram_users.get_or_create(telegram_id=telegram_id, username=None, now=utcnow())
        await self.telegram_users.add_link_if_missing(user.id, normalized_tag, utcnow())
        await self.session.commit()
        return AdminPlayerLinkResult(
            telegram_id=telegram_id,
            player_tag=normalized_tag,
            player_name=player.name,
            already_linked=False,
        )
