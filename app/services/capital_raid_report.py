from __future__ import annotations

from collections import defaultdict

from app.config.settings import AppYamlConfig
from app.repositories.capital_raid import CapitalRaidRepository
from app.repositories.player_capital_contribution_snapshot import PlayerCapitalContributionSnapshotRepository


class CapitalRaidReportService:
    def __init__(self, session, config: AppYamlConfig) -> None:
        self.repo = CapitalRaidRepository(session)
        self.snapshot_repo = PlayerCapitalContributionSnapshotRepository(session)
        self.config = config

    async def get_latest_completed_weekend(self, clan_tag: str):
        return await self.repo.get_latest_completed_weekend(clan_tag)

    async def build_latest_weekend_report(self) -> str:
        weekend = await self.get_latest_completed_weekend(self.config.main_clan_tag)
        if weekend is None:
            return "⚠️ По клановой столице пока нет сохраненных данных."
        participants = await self.repo.list_participants_for_weekend(weekend.id)
        participants.sort(key=lambda p: (-p.capital_resources_looted, -p.attacks, p.player_name))
        start = weekend.start_time.date().isoformat() if weekend.start_time else "—"
        end = weekend.end_time.date().isoformat() if weekend.end_time else "—"
        lines = [
            "🏰 Клановая столица",
            f"📅 {start} — {end}",
            "",
        ]
        for idx, p in enumerate(participants, start=1):
            lines.append(
                f"{idx}. {p.player_name} — атак: {p.attacks}, бонусных: {p.bonus_attacks}, золото: {p.capital_resources_looted}"
            )
        return "\n".join(lines)

    async def build_recent_weekends_report(self, count: int) -> str:
        weekends = await self.repo.list_latest_completed_weekends(self.config.main_clan_tag, limit=10)
        if not weekends:
            return "⚠️ По клановой столице пока нет сохраненных данных."
        if count > len(weekends):
            return f"⚠️ В базе сейчас доступно только {len(weekends)} завершенных рейдов."
        selected = weekends[:count]
        weekend_ids = [w.id for w in selected]
        participants = await self.repo.list_participants_for_weekend_ids(weekend_ids)
        newest_end = max(w.end_time for w in selected if w.end_time is not None)
        oldest_end = min(w.end_time for w in selected if w.end_time is not None)
        oldest_start = min(w.start_time for w in selected if w.start_time is not None)
        player_stats: dict[str, dict[str, int | str]] = defaultdict(lambda: {
            "player_name": "",
            "attacks": 0,
            "bonus_attacks": 0,
            "capital_resources_looted": 0,
            "invested_gold": 0,
        })
        for p in participants:
            row = player_stats[p.player_tag]
            row["player_name"] = p.player_name
            row["attacks"] = int(row["attacks"]) + p.attacks
            row["bonus_attacks"] = int(row["bonus_attacks"]) + p.bonus_attacks
            row["capital_resources_looted"] = int(row["capital_resources_looted"]) + p.capital_resources_looted
        for player_tag, row in player_stats.items():
            base = await self.snapshot_repo.get_first_at_or_after(player_tag, self.config.main_clan_tag, oldest_end)
            latest = await self.snapshot_repo.get_latest(player_tag, self.config.main_clan_tag)
            if base is None or latest is None:
                row["invested_gold"] = 0
                continue
            row["invested_gold"] = max(latest.value - base.value, 0)
        sorted_rows = sorted(
            player_stats.values(),
            key=lambda p: (-int(p["capital_resources_looted"]), -int(p["attacks"]), str(p["player_name"])),
        )
        lines = [
            "🏰 Клановая столица",
            f"📚 Последние {count} рейдов",
            f"📅 {oldest_start.date().isoformat()} — {newest_end.date().isoformat()}",
            "",
        ]
        for idx, row in enumerate(sorted_rows, start=1):
            lines.append(
                f"{idx}. {row['player_name']} — атак: {row['attacks']}, бонусных: {row['bonus_attacks']}, налутал: {row['capital_resources_looted']}, вложил: {row['invested_gold']}"
            )
        return "\n".join(lines)
