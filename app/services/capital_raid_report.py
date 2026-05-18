from __future__ import annotations

from app.config.settings import AppYamlConfig
from app.repositories.capital_raid import CapitalRaidRepository


class CapitalRaidReportService:
    def __init__(self, session, config: AppYamlConfig) -> None:
        self.repo = CapitalRaidRepository(session)
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
