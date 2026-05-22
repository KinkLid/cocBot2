from __future__ import annotations

from collections import defaultdict
import logging

from app.config.settings import AppYamlConfig
from app.repositories.capital_raid import CapitalRaidRepository
from app.repositories.player_capital_contribution_snapshot import PlayerCapitalContributionSnapshotRepository

logger = logging.getLogger(__name__)


class CapitalRaidReportService:
    def __init__(self, session, config: AppYamlConfig) -> None:
        self.repo = CapitalRaidRepository(session)
        self.snapshot_repo = PlayerCapitalContributionSnapshotRepository(session)
        self.config = config

    async def get_latest_completed_weekend(self, clan_tag: str):
        return await self.repo.get_latest_completed_weekend(clan_tag)

    async def build_latest_weekend_report(self) -> str:
        return await self.build_recent_weekends_report(1)

    async def build_recent_weekends_report(self, count: int) -> str:
        available_count = await self.repo.count_completed_weekends(self.config.main_clan_tag)
        weekends = await self.repo.list_latest_completed_weekends(self.config.main_clan_tag, limit=10)
        if not weekends:
            return "⚠️ По клановой столице пока нет сохраненных данных."
        if count > len(weekends):
            return f"⚠️ В базе сейчас доступно только {len(weekends)} завершенных рейдов."
        selected = weekends[:count]
        selected_weekend_ids = [w.id for w in selected]
        participants = await self.repo.list_participants_for_weekend_ids(selected_weekend_ids)
        selected_weekends_count = len(selected)
        weekend_ids_with_participants = {p.weekend_id for p in participants}
        weekends_with_data_count = len(weekend_ids_with_participants)
        empty_weekends_count = selected_weekends_count - weekends_with_data_count
        empty_weekends = [w for w in selected if w.id not in weekend_ids_with_participants]
        if selected_weekends_count > 0 and empty_weekends_count > 0:
            logger.warning(
                "Capital raid report warning: selected=%s, with_data=%s, empty=%s",
                selected_weekends_count,
                weekends_with_data_count,
                empty_weekends_count,
            )
            logger.debug(
                "Capital raid report empty weekends: %s",
                [
                    f"{w.start_time.date().isoformat() if w.start_time else '—'} — {w.end_time.date().isoformat() if w.end_time else '—'}"
                    for w in empty_weekends
                ],
            )
        if weekends_with_data_count == 0:
            return "⚠️ По выбранным рейдам в базе нет данных участников клановой столицы."
        newest_end = max(w.end_time for w in selected if w.end_time is not None)
        oldest_end = min(w.end_time for w in selected if w.end_time is not None)
        oldest_start = min(w.start_time for w in selected if w.start_time is not None)
        player_stats: dict[str, dict[str, int | str]] = defaultdict(lambda: {
            "player_name": "",
            "attacks": 0,
            "bonus_attacks": 0,
            "capital_resources_looted": 0,
            "invested_gold": 0,
            "invested_gold_suffix": "",
        })
        has_insufficient_history = False
        for p in participants:
            row = player_stats[p.player_tag]
            row["player_name"] = p.player_name
            row["attacks"] = int(row["attacks"]) + p.attacks
            row["bonus_attacks"] = int(row["bonus_attacks"]) + p.bonus_attacks
            row["capital_resources_looted"] = int(row["capital_resources_looted"]) + p.capital_resources_looted
        for player_tag, row in player_stats.items():
            snapshots_count = await self.snapshot_repo.count_for_player(player_tag, self.config.main_clan_tag)
            base = await self.snapshot_repo.get_first_at_or_after(player_tag, self.config.main_clan_tag, oldest_end)
            latest = await self.snapshot_repo.get_latest_at_or_before(player_tag, self.config.main_clan_tag, newest_end)
            if base is None or latest is None:
                row["invested_gold"] = 0
                if snapshots_count < 2:
                    row["invested_gold_suffix"] = "*"
                    has_insufficient_history = True
                continue
            row["invested_gold"] = max(latest.value - base.value, 0)
            if snapshots_count < 2:
                row["invested_gold_suffix"] = "*"
                has_insufficient_history = True
        sorted_rows = sorted(
            player_stats.values(),
            key=lambda p: (-int(p["capital_resources_looted"]), -int(p["attacks"]), str(p["player_name"])),
        )
        lines = [
            "🏰 Клановая столица",
            f"📦 В базе завершенных рейдов: {available_count}",
            f"📚 Запрошено последних рейдов: {count}",
            f"✅ Рейдов с данными участников: {weekends_with_data_count}",
            f"⚠️ Пустых рейдов без данных участников: {empty_weekends_count}",
            f"📅 {oldest_start.date().isoformat()} — {newest_end.date().isoformat()}",
            "",
        ]
        if empty_weekends_count > 0:
            lines.append("⚠️ Рейды без данных:")
            for weekend in empty_weekends:
                start = weekend.start_time.date().isoformat() if weekend.start_time else "—"
                end = weekend.end_time.date().isoformat() if weekend.end_time else "—"
                lines.append(f"- {start} — {end}")
            lines.append("")
        for idx, row in enumerate(sorted_rows, start=1):
            lines.append(
                f"{idx}. {row['player_name']} — атак: {row['attacks']}, бонусных: {row['bonus_attacks']}, налутал: {row['capital_resources_looted']}, вложил: {row['invested_gold']}{row['invested_gold_suffix']}"
            )
        if has_insufficient_history:
            lines.extend([
                "",
                "* по этим игрокам пока недостаточно накопленных snapshot’ов для точного расчета вложений",
            ])
        return "\n".join(lines)
