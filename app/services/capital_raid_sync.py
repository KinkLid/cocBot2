from __future__ import annotations

from app.clients.clash import ClashApiClient
from app.config.settings import AppYamlConfig
from app.models import CapitalRaidParticipant, CapitalRaidWeekend
from app.repositories.capital_raid import CapitalRaidRepository
from app.repositories.player_account import PlayerAccountRepository
from app.utils.time import parse_coc_time, utcnow


class CapitalRaidSyncService:
    def __init__(self, session, clash_client: ClashApiClient, config: AppYamlConfig) -> None:
        self.session = session
        self.client = clash_client
        self.config = config
        self.repo = CapitalRaidRepository(session)
        self.players = PlayerAccountRepository(session)

    async def sync_finished(self) -> None:
        seasons = await self.client.get_capital_raid_seasons(self.config.main_clan_tag, limit=10)
        now = utcnow()
        for season in seasons:
            end_time = parse_coc_time(season.end_time)
            if end_time is None or end_time > now:
                continue
            raid_season_id = f"{season.start_time or 'unknown'}:{season.end_time or 'unknown'}"
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
            participants = []
            for m in season.members:
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
                    capital_resources_looted=m.capital_resources_looted,
                    clan_capital_contributions_snapshot=snapshot,
                ))
            await self.repo.replace_participants(weekend.id, participants)
        await self.session.commit()
