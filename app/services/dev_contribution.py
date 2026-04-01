from __future__ import annotations

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.domain.dev_contribution import ContributionInput, DevContributionFormula
from app.repositories.stats import StatsRepository


class DevContributionService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = StatsRepository(session)
        self.formula = DevContributionFormula()

    async def report(self, period_start, period_end) -> str:
        stats_rows = await self.repo.aggregated_player_stats(
            clan_tag=self.config.main_clan_tag,
            period_start=period_start,
            period_end=period_end,
        )
        player_tags = [row.player_tag for row in stats_rows]
        attacks_rows = await self.repo.attack_rows_for_players(self.config.main_clan_tag, period_start, period_end, player_tags)
        score_by_player: dict[str, float] = defaultdict(float)
        lines = [f"🧪 Dev-вклад за период {period_start:%Y-%m-%d} — {period_end:%Y-%m-%d}", ""]

        for attack, _war, _violation in attacks_rows:
            result = self.formula.calculate(
                ContributionInput(
                    stars=attack.stars,
                    attacker_position=attack.attacker_position,
                    attacker_town_hall=attack.attacker_town_hall,
                    defender_town_hall=attack.defender_town_hall,
                    defender_position=attack.defender_position,
                    destruction=attack.destruction,
                )
            )
            score_by_player[attack.attacker_tag] += result.score

        for row in sorted(stats_rows, key=lambda item: score_by_player.get(item.player_tag, 0.0), reverse=True):
            lines.append(f"{row.player_name} {row.player_tag} — {score_by_player.get(row.player_tag, 0.0):.2f}")
        return "\n".join(lines)
