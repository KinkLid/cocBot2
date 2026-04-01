from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.clash import ClashApiClient
from app.repositories.player_account import PlayerAccountRepository
from app.repositories.telegram_user import TelegramUserRepository
from app.utils.tag import normalize_tag
from app.utils.time import utcnow


@dataclass(slots=True)
class RegistrationResult:
    telegram_id: int
    player_tag: str
    player_name: str
    already_linked: bool


class UserAlreadyRegisteredError(ValueError):
    pass


class RegistrationService:
    def __init__(self, session: AsyncSession, clash_client: ClashApiClient) -> None:
        self.session = session
        self.clash_client = clash_client
        self.telegram_users = TelegramUserRepository(session)
        self.players = PlayerAccountRepository(session)

    async def is_registered(self, telegram_id: int) -> bool:
        return await self.telegram_users.is_registered(telegram_id)

    async def register_player(
        self, *, telegram_id: int, username: str | None, player_tag: str, player_token: str, allow_existing_user: bool = False
    ) -> RegistrationResult:
        now = utcnow()
        player_tag = normalize_tag(player_tag)
        if not allow_existing_user and await self.is_registered(telegram_id):
            raise UserAlreadyRegisteredError("Повторная регистрация не требуется")

        is_valid = await self.clash_client.verify_player_token(player_tag, player_token)
        if not is_valid:
            raise ValueError("Неверный player token")

        profile = await self.clash_client.get_player(player_tag)
        tg_user = await self.telegram_users.get_or_create(telegram_id=telegram_id, username=username, now=now)
        await self.players.upsert_player(
            player_tag=profile.tag,
            name=profile.name,
            town_hall=profile.town_hall,
            now=now,
            clan_tag=None,
            clan_name=None,
            clan_rank=None,
            in_clan=False,
        )
        existing_links = await self.telegram_users.get_links(tg_user.id)
        already_linked = any(link.player_tag == profile.tag for link in existing_links)
        await self.telegram_users.add_link_if_missing(tg_user.id, profile.tag, now)
        await self.session.commit()
        return RegistrationResult(
            telegram_id=telegram_id,
            player_tag=profile.tag,
            player_name=profile.name,
            already_linked=already_linked,
        )

    async def add_player_account(
        self, *, telegram_id: int, username: str | None, player_tag: str, player_token: str
    ) -> RegistrationResult:
        return await self.register_player(
            telegram_id=telegram_id,
            username=username,
            player_tag=player_tag,
            player_token=player_token,
            allow_existing_user=True,
        )
