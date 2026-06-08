from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import floor

from app.config.settings import AppYamlConfig
from app.repositories.capital_raid import CapitalRaidRepository


CAPITAL_UNDER_5_ATTACKS = "capital_under_5_attacks"
CAPITAL_UNDER_5_ATTACKS_REASON = "Игрок сделал меньше 5 атак в рейде столицы"


def calculate_capital_weekend_score(
    *, attacks: int, districts_destroyed: int, total_destruction_percent: int
) -> float:
    if attacks < 5:
        return 0.0
    score = attacks * 1.5 + 3
    if attacks >= 6:
        score += 2
    score += districts_destroyed
    score += floor(total_destruction_percent / 100) * 0.5
    return float(score)


@dataclass(slots=True)
class CapitalContributionCycleStats:
    total_completed_weekends: int
    weekends_with_participants: int
    weekends_without_participants: int


class CapitalRaidContributionService:
    def __init__(self, session, config: AppYamlConfig) -> None:
        self.repo = CapitalRaidRepository(session)
        self.config = config

    async def build_current_cycle_ranking(self, period):
        weekends = await self.repo.list_weekends_for_period(
            self.config.main_clan_tag, period.start, period.end
        )
        total_completed_weekends = len(weekends)
        weekend_ids = {weekend.id for weekend in weekends}
        participants = await self.repo.list_participants_for_weekend_ids(list(weekend_ids))
        weekends_with_participants = len(
            {participant.weekend_id for participant in participants if participant.weekend_id in weekend_ids}
        )
        weekends_without_participants = total_completed_weekends - weekends_with_participants
        rows = defaultdict(
            lambda: {
                "player_tag": "",
                "player_name": "",
                "weekends_count": 0,
                "attacks": 0,
                "districts_destroyed": 0,
                "total_destruction_percent": 0,
                "violations": 0,
                "score": 0.0,
            }
        )
        for participant in participants:
            row = rows[participant.player_tag]
            row["player_tag"] = participant.player_tag
            row["player_name"] = participant.player_name
            row["weekends_count"] += 1
            row["attacks"] += participant.attacks
            row["districts_destroyed"] += participant.districts_destroyed
            row["total_destruction_percent"] += participant.total_destruction_percent
            if participant.attacks < 5:
                row["violations"] += 1
            row["score"] += calculate_capital_weekend_score(
                attacks=participant.attacks,
                districts_destroyed=participant.districts_destroyed,
                total_destruction_percent=participant.total_destruction_percent,
            )

        ranking = list(rows.values())
        ranking.sort(
            key=lambda row: (
                -float(row["score"]),
                -int(row["attacks"]),
                -int(row["districts_destroyed"]),
                str(row["player_name"]),
            )
        )
        return ranking, CapitalContributionCycleStats(
            total_completed_weekends=total_completed_weekends,
            weekends_with_participants=weekends_with_participants,
            weekends_without_participants=weekends_without_participants,
        )

    def format_current_cycle_ranking(self, period, ranking, stats: CapitalContributionCycleStats) -> str:
        if stats.total_completed_weekends == 0:
            return "⚠️ По клановой столице за текущий цикл пока нет данных."
        if stats.weekends_with_participants == 0:
            return "⚠️ В текущем цикле есть завершенные рейды столицы, но по ним нет данных участников."
        lines = [
            "🧪 Dev вклад в столицу",
            f"📅 {period.start.date().isoformat()} — {period.end.date().isoformat()}",
            f"📦 Завершенных рейдов в цикле: {stats.total_completed_weekends}",
            f"✅ Рейдов с данными участников: {stats.weekends_with_participants}",
        ]
        if stats.weekends_without_participants > 0:
            lines.append(f"⚠️ Рейдов без данных участников: {stats.weekends_without_participants}")
        lines.append("")
        for index, row in enumerate(ranking, 1):
            lines.append(
                f"{index}. {row['player_name']} — {float(row['score']):.1f} | "
                f"рейдов: {row['weekends_count']}, атак: {row['attacks']}, "
                f"добиваний: {row['districts_destroyed']}, "
                f"разрушение: {row['total_destruction_percent']}%, нарушений: {row['violations']}"
            )
        return "\n".join(lines)
