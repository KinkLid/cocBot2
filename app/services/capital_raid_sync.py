from __future__ import annotations

import logging

from app.clients.clash import ClashApiClient
from app.config.settings import AppYamlConfig
from app.models import CapitalRaidParticipant, CapitalRaidWeekend
from app.repositories.capital_raid import CapitalRaidRepository
from app.repositories.player_account import PlayerAccountRepository
from app.repositories.player_capital_contribution_snapshot import PlayerCapitalContributionSnapshotRepository
from app.utils.time import parse_coc_time, utcnow


logger = logging.getLogger(__name__)


class CapitalRaidSyncService:
    def __init__(self, session, clash_client: ClashApiClient, config: AppYamlConfig) -> None:
        self.session = session
        self.client = clash_client
        self.config = config
        self.repo = CapitalRaidRepository(session)
        self.players = PlayerAccountRepository(session)
        self.snapshots = PlayerCapitalContributionSnapshotRepository(session)

    async def sync_finished(self) -> None:
        seasons = await self.client.get_capital_raid_seasons(self.config.main_clan_tag, limit=10)
        now = utcnow()
        api_total = len(seasons)
        ended_from_api = 0
        created = 0
        updated = 0
        backfilled = 0
        participants_saved = 0
        snapshots_saved = 0
        for season in seasons:
            end_time = parse_coc_time(season.end_time)
            if end_time is None or end_time > now:
                continue
            ended_from_api += 1
            raid_season_id = f"{season.start_time or 'unknown'}:{season.end_time or 'unknown'}"
            existing_weekend = await self.repo.get_weekend(self.config.main_clan_tag, raid_season_id)
            existed_before = existing_weekend is not None
            logger.debug(
                "Capital raid season processing: raid_season_id=%s, start_time=%s, end_time=%s, state=%s, members_count=%s, existed_before=%s",
                raid_season_id,
                season.start_time,
                season.end_time,
                season.state,
                len(season.members),
                existed_before,
            )
            weekend = await self.repo.upsert_weekend(CapitalRaidWeekend(
                clan_tag=self.config.main_clan_tag,
                raid_season_id=raid_season_id,
                state=season.state,
                start_time=parse_coc_time(season.start_time),
                end_time=end_time,
                total_loot=season.total_loot,
                total_attacks=season.total_attacks,
                enemy_districts_destroyed=season.enemy_districts_destroyed,
                offensive_reward=season.offensive_reward,
                defensive_reward=season.defensive_reward,
                processed_at=now,
            ))
            first_processed = not existed_before
            participants_count = await self.repo.count_participants_for_weekend(weekend.id)
            should_backfill = existed_before and participants_count == 0
            if first_processed:
                created += 1
            else:
                updated += 1
                if should_backfill:
                    backfilled += 1
            participants = []
            for m in season.members:
                participants_saved += 1
                player = await self.players.get_by_tag(m.tag)
                snapshot = None
                try:
                    profile = await self.client.get_player(m.tag)
                    snapshot = getattr(profile, "clan_capital_contributions", None)
                except Exception:
                    snapshot = None
                participants.append(CapitalRaidParticipant(
                    weekend_id=weekend.id,
                    player_id=player.id if player else None,
                    player_tag=m.tag,
                    player_name=m.name,
                    attacks=m.attacks,
                    attack_limit=m.attack_limit,
                    bonus_attacks=m.bonus_attacks,
                    districts_destroyed=m.districts_destroyed,
                    capital_resources_looted=m.capital_resources_looted,
                    clan_capital_contributions_snapshot=snapshot,
                ))
                if (first_processed or should_backfill) and snapshot is not None:
                    await self.snapshots.add(
                        player_tag=m.tag,
                        clan_tag=self.config.main_clan_tag,
                        observed_at=weekend.processed_at,
                        value=snapshot,
                    )
                    snapshots_saved += 1
            await self.repo.replace_participants(weekend.id, participants)
        await self.session.commit()
        count_db_completed = await self.repo.count_completed_weekends(self.config.main_clan_tag)
        logger.info(
            "Capital raid sync: api_total=%s, ended=%s, created=%s, updated=%s, backfilled=%s, participants_saved=%s, snapshots_saved=%s",
            api_total,
            ended_from_api,
            created,
            updated,
            backfilled,
            participants_saved,
            snapshots_saved,
        )
        if ended_from_api > 1 and count_db_completed < ended_from_api and count_db_completed == 1:
            logger.warning(
                "Capital raid sync warning: API returned %s ended weekends, but only %s completed weekend is present in DB after sync",
                ended_from_api,
                count_db_completed,
            )

    async def repair_current_cycle_missing_participants(self, period) -> None:
        now = utcnow()
        upper_bound = min(period.end, now)
        weekends = await self.repo.list_weekends_for_period(self.config.main_clan_tag, period.start, upper_bound)
        empty_weekends = []
        for weekend in weekends:
            if await self.repo.count_participants_for_weekend(weekend.id) == 0:
                empty_weekends.append(weekend)
        if not empty_weekends:
            logger.info("Capital raid repair: empty_weekends=0, backfilled=0, participants_saved=0")
            return

        seasons = await self.client.get_capital_raid_seasons(self.config.main_clan_tag, limit=10)
        ended = {}
        for season in seasons:
            end_time = parse_coc_time(season.end_time)
            if end_time is None or end_time > now:
                continue
            raid_season_id = f"{season.start_time or 'unknown'}:{season.end_time or 'unknown'}"
            ended[raid_season_id] = season

        backfilled = 0
        participants_saved = 0
        snapshots_saved = 0
        for weekend in empty_weekends:
            season = ended.get(weekend.raid_season_id)
            if season is None:
                continue
            participants = []
            for m in season.members:
                participants_saved += 1
                player = await self.players.get_by_tag(m.tag)
                snapshot = None
                try:
                    profile = await self.client.get_player(m.tag)
                    snapshot = getattr(profile, "clan_capital_contributions", None)
                except Exception:
                    snapshot = None
                participants.append(CapitalRaidParticipant(
                    weekend_id=weekend.id,
                    player_id=player.id if player else None,
                    player_tag=m.tag,
                    player_name=m.name,
                    attacks=m.attacks,
                    attack_limit=m.attack_limit,
                    bonus_attacks=m.bonus_attacks,
                    districts_destroyed=m.districts_destroyed,
                    capital_resources_looted=m.capital_resources_looted,
                    clan_capital_contributions_snapshot=snapshot,
                ))
                if snapshot is not None:
                    await self.snapshots.add(
                        player_tag=m.tag,
                        clan_tag=self.config.main_clan_tag,
                        observed_at=weekend.processed_at,
                        value=snapshot,
                    )
                    snapshots_saved += 1
            await self.repo.replace_participants(weekend.id, participants)
            backfilled += 1

        await self.session.commit()
        logger.info(
            "Capital raid repair: empty_weekends=%s, backfilled=%s, participants_saved=%s, snapshots_saved=%s",
            len(empty_weekends),
            backfilled,
            participants_saved,
            snapshots_saved,
        )
