from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.clash import ClashApiClient
from app.config.settings import AppYamlConfig
from app.models import DepartedPlayerArchive, ReturnEvent
from app.repositories.player_account import PlayerAccountRepository
from app.services.notifications import AdminNotifier
from app.services.donations import DonationService
from app.services.period import PeriodService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingReturnNotification:
    player_tag: str
    player_name: str
    event_key: str
    event_type: str
    text: str
    created_at: datetime


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
        self.donations = DonationService(session, config)

    async def sync_members(self) -> int:
        now = utcnow()
        clan_info = await self.clash_client.get_clan(self.config.main_clan_tag)
        members = await self.clash_client.get_clan_members(self.config.main_clan_tag)
        expected_member_count = clan_info.get("members")
        member_tags = [member.tag for member in members]
        current_tags = set(member_tags)

        if len(current_tags) != len(member_tags):
            raise ValueError("Duplicate clan roster response: endpoint returned duplicate member tags")
        if isinstance(expected_member_count, int) and len(current_tags) != expected_member_count:
            raise ValueError(
                "Incomplete clan roster response: "
                f"clan reports {expected_member_count} members, endpoint returned {len(current_tags)} unique members"
            )

        pending_return_notifications: list[PendingReturnNotification] = []
        added = 0
        returned = 0
        departed = 0

        for member in members:
            existing = await self.players.get_by_tag(member.tag)
            returned_from_archive = await self.session.scalar(
                select(DepartedPlayerArchive).where(DepartedPlayerArchive.player_tag == member.tag)
            )
            was_absent = existing is not None and not existing.current_in_clan
            if existing is None:
                added += 1

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
                returned += 1
                was_purged = returned_from_archive is not None
                self.session.add(ReturnEvent(player_tag=member.tag, player_name=member.name, returned_at=now, was_purged=was_purged))
                if returned_from_archive is not None:
                    await self.session.delete(returned_from_archive)
                pending_return_notifications.append(
                    PendingReturnNotification(
                        player_tag=member.tag,
                        player_name=member.name,
                        event_key=f"return:{member.tag}:{now.date().isoformat()}",
                        event_type="return",
                        text=f"🔁 Игрок вернулся в клан: {member.name} {member.tag}",
                        created_at=now,
                    )
                )
                logger.info("Return detected for %s", member.tag)

        active_members = await self.players.active_clan_members(self.config.main_clan_tag)
        for player in active_members:
            if player.player_tag in current_tags:
                continue
            departed += 1
            await self.players.mark_absent(player, now)
            await self.players.close_membership(player.id, self.config.main_clan_tag, now)
            logger.info("Player left clan: %s", player.player_tag)

        await self.session.commit()

        active_members_after_commit = await self.players.active_clan_members(self.config.main_clan_tag)
        active_db_tags = {player.player_tag for player in active_members_after_commit}
        if active_db_tags != current_tags:
            missing = sorted(current_tags - active_db_tags)
            extra = sorted(active_db_tags - current_tags)
            logger.error("Clan roster mismatch after commit: missing=%s extra=%s", missing, extra)
            raise RuntimeError("Clan roster mismatch after commit")

        logger.info(
            "Clan roster synchronized: api_expected=%s api_received=%s active_in_db=%s added=%s returned=%s departed=%s",
            expected_member_count,
            len(current_tags),
            len(active_db_tags),
            added,
            returned,
            departed,
        )

        await self._send_return_notifications_best_effort(pending_return_notifications)
        await self._record_donation_snapshots_best_effort(members)
        await self._purge_absent_players_best_effort(now)
        return len(members)

    async def _send_return_notifications_best_effort(self, notifications: list[PendingReturnNotification]) -> None:
        for notification in notifications:
            try:
                await self.notifier.notify_once(
                    event_key=notification.event_key,
                    event_type=notification.event_type,
                    text=notification.text,
                    now=notification.created_at,
                )
            except Exception:
                await self.session.rollback()
                logger.warning(
                    "Failed to send return notification: player_tag=%s event_key=%s",
                    notification.player_tag,
                    notification.event_key,
                    exc_info=True,
                )

    async def _record_donation_snapshots_best_effort(self, members) -> None:
        for member in members:
            try:
                profile = await self.clash_client.get_player(member.tag)
            except Exception:
                logger.warning(
                    "Failed to load player profile for donation snapshot: %s",
                    member.tag,
                    exc_info=True,
                )
                continue

            try:
                player = await self.players.get_by_tag(member.tag)
                if player is None:
                    logger.warning("Skipping donation snapshot for missing player after roster sync: %s", member.tag)
                    continue
                await self.donations.record_snapshot(
                    player_tag=member.tag,
                    player_id=player.id,
                    clan_tag=self.config.main_clan_tag,
                    donations=profile.donations,
                    donations_received=profile.donations_received,
                )
                await self.session.commit()
            except Exception:
                await self.session.rollback()
                logger.warning("Failed to record donation snapshot: %s", member.tag, exc_info=True)

    async def _purge_absent_players_best_effort(self, now) -> None:
        try:
            await self._purge_players_absent_full_cycle(now)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception("Failed to purge players absent for a full cycle")

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
