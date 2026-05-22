from __future__ import annotations

from collections import defaultdict
from math import floor

from app.config.settings import AppYamlConfig
from app.repositories.capital_raid import CapitalRaidRepository
from app.repositories.player_capital_contribution_snapshot import PlayerCapitalContributionSnapshotRepository


class CapitalRaidContributionService:
    def __init__(self, session, config: AppYamlConfig) -> None:
        self.repo = CapitalRaidRepository(session)
        self.snapshot_repo = PlayerCapitalContributionSnapshotRepository(session)
        self.config = config

    async def build_current_cycle_ranking(self, period):
        weekends = await self.repo.list_weekends_for_period(self.config.main_clan_tag, period.start, period.end)
        if not weekends:
            return [], False
        participants = await self.repo.list_participants_for_period(self.config.main_clan_tag, period.start, period.end)
        rows = defaultdict(lambda: {"player_name": "", "attacks": 0, "bonus_attacks": 0, "districts_destroyed": 0, "capital_resources_looted": 0, "invested_gold": 0, "invested_gold_suffix": "", "score": 0.0})
        for p in participants:
            row = rows[p.player_tag]
            row["player_name"] = p.player_name
            row["attacks"] += p.attacks
            row["bonus_attacks"] += p.bonus_attacks
            row["districts_destroyed"] += p.districts_destroyed
            row["capital_resources_looted"] += p.capital_resources_looted

        ranking = []
        destroy_stats_available = any(int(r["districts_destroyed"]) > 0 for r in rows.values())
        for player_tag, row in rows.items():
            base = await self.snapshot_repo.get_first_at_or_after(player_tag, self.config.main_clan_tag, period.start)
            latest = await self.snapshot_repo.get_latest_at_or_before(player_tag, self.config.main_clan_tag, period.end)
            if base is None or latest is None:
                row["invested_gold"] = 0
                row["invested_gold_suffix"] = "*"
            else:
                row["invested_gold"] = max(latest.value - base.value, 0)
            attacks = int(row["attacks"])
            districts = int(row["districts_destroyed"])
            looted = int(row["capital_resources_looted"])
            invested = int(row["invested_gold"])
            score = attacks * 1.5
            if attacks >= 5:
                score += 3
            if attacks >= 6:
                score += 2
            score += floor(looted / 5000)
            score += floor(invested / 10000)
            if destroy_stats_available:
                score += districts
                if districts < 2:
                    score -= 4
            if attacks < 5:
                score -= 3
            row["score"] = score
            ranking.append(row)

        ranking.sort(key=lambda r: (-float(r["score"]), -int(r["capital_resources_looted"]), -int(r["attacks"]), str(r["player_name"])))
        return ranking, destroy_stats_available

    def format_current_cycle_ranking(self, period, ranking, destroy_stats_available: bool) -> str:
        if not ranking:
            return "⚠️ По клановой столице за текущий цикл пока нет данных."
        lines = ["🧪 Dev-столица", f"📅 {period.start.date().isoformat()} — {period.end.date().isoformat()}", ""]
        has_star = False
        for idx, row in enumerate(ranking, 1):
            destroy = str(row["districts_destroyed"]) if destroy_stats_available else "—"
            suffix = row["invested_gold_suffix"]
            if suffix:
                has_star = True
            lines.append(f"{idx}. {row['player_name']} — {float(row['score']):.2f} | атак: {row['attacks']}, добиваний: {destroy}, налутал: {row['capital_resources_looted']}, вложил: {row['invested_gold']}{suffix}")
        if not destroy_stats_available:
            lines.extend(["", "добивания районов сейчас не учитываются: в сохраненных данных нет надежной статистики по добиваниям"])
        if has_star:
            lines.extend(["", "* по этим игрокам пока недостаточно накопленных snapshot’ов для точного расчета вложений"])
        return "\n".join(lines)
