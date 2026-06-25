from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.models.enums import ViolationCode, WarType
from app.repositories.capital_raid import CapitalRaidRepository
from app.repositories.capital_raid_violation import CapitalRaidViolationRepository
from app.repositories.stats import StatsRepository
from app.repositories.war import WarRepository
from app.schemas.dto import AttackExportDTO, CapitalParticipationExportDTO, PlayerExportDTO, WarParticipationExportDTO
from app.services.capital_raid_contribution import (
    CAPITAL_UNDER_5_ATTACKS,
    CAPITAL_UNDER_5_ATTACKS_REASON,
    calculate_capital_weekend_score,
)
from app.services.stats import StatsService


class ExportService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.stats_repo = StatsRepository(session)
        self.stats_service = StatsService(session, config)
        self.war_repo = WarRepository(session)
        self.capital_repo = CapitalRaidRepository(session)
        self.capital_violation_repo = CapitalRaidViolationRepository(session)

    async def export_to_dict(self, period_start, period_end) -> dict:
        clan_stats = await self.stats_service.clan_stats(period_start, period_end)
        player_tags = [row.player_tag for row in clan_stats.rows]
        attacks_rows = await self.stats_repo.attack_rows_for_players(self.config.main_clan_tag, period_start, period_end, player_tags)
        participation_rows = await self.stats_repo.participation_rows_for_players(self.config.main_clan_tag, period_start, period_end, player_tags)
        capital_weekends = await self.capital_repo.list_weekends_for_period(
            self.config.main_clan_tag, period_start, period_end
        )
        capital_participants = await self.capital_repo.list_participants_for_weekend_ids(
            [weekend.id for weekend in capital_weekends]
        )
        capital_violations = await self.capital_violation_repo.list_for_weekend_ids(
            [weekend.id for weekend in capital_weekends]
        )
        war_ids = list({war.id for _, war in participation_rows})
        war_violations = await self.war_repo.list_violations_for_war_ids(war_ids)
        cwl_missed_by_war_player = {
            (violation.war_id, violation.player_tag): violation
            for violation in war_violations
            if violation.code == ViolationCode.CWL_MISSED_ATTACK
        }

        attacks_by_player_and_war: dict[tuple[str, int], list[AttackExportDTO]] = defaultdict(list)
        for attack, war, violation in attacks_rows:
            attacks_by_player_and_war[(attack.attacker_tag, war.id)].append(
                AttackExportDTO(
                    observed_at=attack.observed_at,
                    war_type=war.war_type,
                    is_cwl=war.war_type == WarType.CWL,
                    attacker_position=attack.attacker_position,
                    defender_position=attack.defender_position,
                    attacker_town_hall=attack.attacker_town_hall,
                    defender_town_hall=attack.defender_town_hall,
                    stars=attack.stars,
                    destruction=attack.destruction,
                    violated=violation is not None,
                    violation_code=violation.code if violation else None,
                    violation_reason=violation.reason_text if violation else None,
                    attacker_tag=attack.attacker_tag,
                    defender_tag=attack.defender_tag,
                    attacker_name=attack.attacker_name,
                    defender_name=attack.defender_name,
                )
            )

        participation_by_player: dict[str, list[WarParticipationExportDTO]] = defaultdict(list)
        for participant, war in participation_rows:
            missed_violation = cwl_missed_by_war_player.get((war.id, participant.player_tag))
            participation_by_player[participant.player_tag].append(
                WarParticipationExportDTO(
                    war_uid=war.war_uid,
                    war_type=war.war_type,
                    start_time=war.start_time,
                    end_time=war.end_time,
                    roster_position=participant.map_position,
                    attacks=attacks_by_player_and_war.get((participant.player_tag, war.id), []),
                    missed_attack_violation=missed_violation is not None,
                    missed_attack_violation_code=missed_violation.code if missed_violation else None,
                    missed_attack_violation_reason=missed_violation.reason_text if missed_violation else None,
                )
            )

        weekends_by_id = {weekend.id: weekend for weekend in capital_weekends}
        violations_by_weekend_player = {
            (violation.weekend_id, violation.player_tag): violation
            for violation in capital_violations
        }
        capital_by_player: dict[str, list[CapitalParticipationExportDTO]] = defaultdict(list)
        for participant in capital_participants:
            weekend = weekends_by_id[participant.weekend_id]
            violation = violations_by_weekend_player.get((participant.weekend_id, participant.player_tag))
            assert weekend.end_time is not None
            violated = participant.attacks < 5
            capital_by_player[participant.player_tag].append(
                CapitalParticipationExportDTO(
                    raid_season_id=weekend.raid_season_id,
                    start_time=weekend.start_time,
                    end_time=weekend.end_time,
                    attacks=participant.attacks,
                    attack_limit=participant.attack_limit,
                    bonus_attacks=participant.bonus_attacks,
                    districts_destroyed=participant.districts_destroyed,
                    total_destruction_percent=participant.total_destruction_percent,
                    capital_resources_looted=participant.capital_resources_looted,
                    violated=violated,
                    violation_code=(violation.code if violation else CAPITAL_UNDER_5_ATTACKS if violated else None),
                    violation_reason=(
                        violation.reason_text
                        if violation
                        else CAPITAL_UNDER_5_ATTACKS_REASON if violated else None
                    ),
                    dev_capital_score=calculate_capital_weekend_score(
                        attacks=participant.attacks,
                        districts_destroyed=participant.districts_destroyed,
                        total_destruction_percent=participant.total_destruction_percent,
                    ),
                )
            )

        players_payload = []
        for row in clan_stats.rows:
            player = PlayerExportDTO(
                player_tag=row.player_tag,
                player_name=row.player_name,
                town_hall=row.town_hall,
                telegram_id=row.telegram_id,
                telegram_username=row.telegram_username,
                registered_at=row.registered_at,
                wars=row.wars,
                attacks=row.attacks,
                stars=row.stars,
                violations=row.violations,
                place=row.place,
                participation=participation_by_player.get(row.player_tag, []),
                capital_participation=capital_by_player.get(row.player_tag, []),
            )
            players_payload.append(player.model_dump(mode="json"))

        return {
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
            },
            "clan": {
                "tag": self.config.main_clan_tag,
            },
            "players": players_payload,
        }

    async def export_to_file(self, period_start, period_end, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = await self.export_to_dict(period_start, period_end)
        output_path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS))
        return output_path
