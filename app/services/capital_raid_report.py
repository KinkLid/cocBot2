from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.config.settings import AppYamlConfig
from app.repositories.capital_raid import CapitalRaidRepository
from app.repositories.capital_raid_violation import CapitalRaidViolationRepository


@dataclass(slots=True)
class CapitalRaidCycleStats:
    completed_weekends: int


class CapitalRaidStatsService:
    def __init__(self, session, config: AppYamlConfig) -> None:
        self.repo = CapitalRaidRepository(session)
        self.violation_repo = CapitalRaidViolationRepository(session)
        self.config = config

    async def build_current_cycle_stats(self, period):
        weekends = await self.repo.list_weekends_for_period(
            self.config.main_clan_tag, period.start, period.end
        )
        participants = await self.repo.list_participants_for_weekend_ids([weekend.id for weekend in weekends])
        violation_counts = await self.violation_repo.aggregated_current_cycle(
            self.config.main_clan_tag, period.start, period.end
        )
        rows = defaultdict(
            lambda: {
                "player_tag": "",
                "player_name": "",
                "weekends_count": 0,
                "attacks": 0,
                "bonus_attacks": 0,
                "districts_destroyed": 0,
                "total_destruction_percent": 0,
                "capital_violation_count": 0,
            }
        )
        for participant in participants:
            row = rows[participant.player_tag]
            row["player_tag"] = participant.player_tag
            row["player_name"] = participant.player_name
            row["weekends_count"] += 1
            row["attacks"] += participant.attacks
            row["bonus_attacks"] += participant.bonus_attacks
            row["districts_destroyed"] += participant.districts_destroyed
            row["total_destruction_percent"] += participant.total_destruction_percent
            row["capital_violation_count"] = violation_counts.get(participant.player_tag, 0)

        result = list(rows.values())
        result.sort(
            key=lambda row: (
                -int(row["attacks"]),
                -int(row["districts_destroyed"]),
                -int(row["total_destruction_percent"]),
                str(row["player_name"]),
            )
        )
        return result, CapitalRaidCycleStats(completed_weekends=len(weekends))

    def format_current_cycle_stats(self, period, rows, stats: CapitalRaidCycleStats) -> str:
        if not rows:
            return "⚠️ По столице за текущий цикл пока нет данных."
        lines = [
            "🏰 Столица",
            f"📅 {period.start.date().isoformat()} — {period.end.date().isoformat()}",
            f"📦 Учтено рейдов столицы: {stats.completed_weekends}",
            "",
        ]
        for index, row in enumerate(rows, 1):
            lines.append(
                f"{index}. {row['player_name']} — рейдов: {row['weekends_count']}, "
                f"атак: {row['attacks']}, добиваний: {row['districts_destroyed']}, "
                f"разрушение: {row['total_destruction_percent']}%, "
                f"нарушений: {row['capital_violation_count']}"
            )
        return "\n".join(lines)


CapitalRaidReportService = CapitalRaidStatsService
