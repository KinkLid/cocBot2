from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.models.enums import WarType
from app.repositories.stats import StatsRepository
from app.schemas.dto import AttackExportDTO, PlayerExportDTO, WarParticipationExportDTO
from app.services.stats import StatsService


class ExportService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.stats_repo = StatsRepository(session)
        self.stats_service = StatsService(session, config)

    async def export_to_dict(self, period_start, period_end) -> dict:
        clan_stats = await self.stats_service.clan_stats(period_start, period_end)
        player_tags = [row.player_tag for row in clan_stats.rows]
        attacks_rows = await self.stats_repo.attack_rows_for_players(self.config.main_clan_tag, period_start, period_end, player_tags)
        participation_rows = await self.stats_repo.participation_rows_for_players(self.config.main_clan_tag, period_start, period_end, player_tags)

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
            participation_by_player[participant.player_tag].append(
                WarParticipationExportDTO(
                    war_uid=war.war_uid,
                    war_type=war.war_type,
                    start_time=war.start_time,
                    end_time=war.end_time,
                    roster_position=participant.map_position,
                    attacks=attacks_by_player_and_war.get((participant.player_tag, war.id), []),
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
