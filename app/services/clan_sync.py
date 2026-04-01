from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.clash import ClashApiClient
from app.config.settings import AppYamlConfig
from app.models import DepartedPlayerArchive, ReturnEvent
from app.repositories.player_account import PlayerAccountRepository
from app.services.notifications import AdminNotifier
from app.services.period import PeriodService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


class ClanSyncService:
    def __init__(
        self,
        session: AsyncSession,
        clash_client: ClashApiClient,
        config: AppYamlConfig,
        notifier: AdminNotifier,
    ) -> None:
        self.session = session
        self.clash_client = clash_client
        self.config = config
        self.notifier = notifier
        self.players = PlayerAccountRepository(session)
        self.period_service = PeriodService(session)

    async def sync_members(self) -> int:
        now = utcnow()
        clan_info = await self.clash_client.get_clan(self.config.main_clan_tag)
        members = await self.clash_client.get_clan_members(self.config.main_clan_tag)
        current_tags = {member.tag for member in members}

        for member in members:
            existing = await self.players.get_by_tag(member.tag)
            returned_from_archive = await self.session.scalar(
                select(DepartedPlayerArchive).where(DepartedPlayerArchive.player_tag == member.tag)
            )
            was_absent = existing is not None and not existing.current_in_clan

            player = await self.players.upsert_player(
                player_tag=member.tag,
                name=member.name,
                town_hall=member.town_hall,
                now=now,
                clan_tag=self.config.main_clan_tag,
                clan_name=clan_info.get("name"),
                clan_rank=member.clan_rank,
                in_clan=True,
            )
            await self.players.open_or_create_membership(player.id, self.config.main_clan_tag, now)

            if returned_from_archive is not None or was_absent:
                was_purged = returned_from_archive is not None
                self.session.add(ReturnEvent(player_tag=member.tag, player_name=member.name, returned_at=now, was_purged=was_purged))
                if returned_from_archive is not None:
                    await self.session.delete(returned_from_archive)
                await self.notifier.notify_once(
                    event_key=f"return:{member.tag}:{now.date().isoformat()}",
                    event_type="return",
                    text=f"🔁 Игрок вернулся в клан: {member.name} {member.tag}",
                    now=now,
                )
                logger.info("Return detected for %s", member.tag)

        active_members = await self.players.active_clan_members(self.config.main_clan_tag)
        for player in active_members:
            if player.player_tag in current_tags:
                continue
            await self.players.mark_absent(player, now)
            await self.players.close_membership(player.id, self.config.main_clan_tag, now)
            logger.info("Player left clan: %s", player.player_tag)

        await self._purge_players_absent_full_cycle(now)
        await self.session.commit()
        return len(members)

    async def _purge_players_absent_full_cycle(self, now) -> None:
        absent_players = await self.players.absent_players()
        try:
            previous_cycle = await self.period_service.previous_cycle(now)
        except ValueError:
            return

        for player in absent_players:
            if player.last_seen_in_clan_at is None:
                continue
            if player.last_seen_in_clan_at > previous_cycle.start:
                continue
            archive_exists = await self.session.scalar(
                select(DepartedPlayerArchive).where(DepartedPlayerArchive.player_tag == player.player_tag)
            )
            if archive_exists is None:
                self.session.add(
                    DepartedPlayerArchive(
                        player_tag=player.player_tag,
                        last_known_name=player.name,
                        previous_clan_tag=self.config.main_clan_tag,
                        departed_at=player.first_absent_at or now,
                        purged_at=now,
                    )
                )
            await self.players.delete_player_fully(player.id)
            logger.info("Player purged after full cycle absence: %s", player.player_tag)
