from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.domain.dev_contribution import ContributionAttackInput, calculate_attack_contribution
from app.models import ClanMembershipHistory
from app.repositories.stats import StatsRepository
from app.utils.time import utcnow


@dataclass(slots=True)
class ContributionRankingRow:
    player_tag: str
    player_name: str
    wars: int
    score: float
    newcomer: bool


class DevContributionService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = StatsRepository(session)

    async def is_newcomer(self, player_id: int, score: float, wars: int) -> bool:
        if score != 0 or wars != 0:
            return False
        membership = await self.session.scalar(
            select(ClanMembershipHistory)
            .where(
                ClanMembershipHistory.player_id == player_id,
                ClanMembershipHistory.clan_tag == self.config.main_clan_tag,
                ClanMembershipHistory.left_at.is_(None),
            )
            .order_by(ClanMembershipHistory.joined_at.desc())
        )
        if membership is None:
            return False
        return (utcnow() - membership.joined_at) < timedelta(days=15)

    async def build_contribution_ranking(self, period) -> list[ContributionRankingRow]:
        stats_rows = await self.repo.aggregated_player_stats(clan_tag=self.config.main_clan_tag, period_start=period.start, period_end=period.end)
        attacks_rows = await self.repo.attack_rows_for_players(self.config.main_clan_tag, period.start, period.end, [r.player_tag for r in stats_rows])
        by_tag: dict[str, float] = {r.player_tag: 0.0 for r in stats_rows}
        for attack, war, violation in attacks_rows:
            by_tag[attack.attacker_tag] += calculate_attack_contribution(
                ContributionAttackInput(
                    stars=attack.stars,
                    destruction=attack.destruction,
                    attacker_position=attack.attacker_position,
                    defender_position=attack.defender_position,
                    is_cwl=war.war_type.value == "cwl",
                    is_above_self_violation=bool(violation and violation.code.value == "above_self"),
                    is_too_low_violation=bool(violation and violation.code.value == "too_low"),
                )
            ).score
        ranking: list[ContributionRankingRow] = []
        for row in stats_rows:
            newcomer = await self.is_newcomer(row.player_id, round(by_tag.get(row.player_tag, 0.0), 2), row.wars) if hasattr(row, "player_id") else False
            ranking.append(ContributionRankingRow(row.player_tag, row.player_name, row.wars, round(by_tag.get(row.player_tag, 0.0), 2), newcomer))
        return sorted(ranking, key=lambda x: x.score, reverse=True)

    def format_contribution_ranking(self, ranking: list[ContributionRankingRow]) -> str:
        lines = ["🏆 Общий вклад", ""]
        for idx, row in enumerate(ranking, 1):
            suffix = " 🆕 новенький" if row.newcomer else ""
            lines.append(f"{idx}. {row.player_name} — {row.score:.2f}{suffix}")
        return "\n".join(lines)
