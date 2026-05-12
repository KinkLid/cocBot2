from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from collections import defaultdict

from app.domain.dev_contribution import (
    ContributionAttackInput,
    calculate_attack_contribution,
    calculate_cwl_unused_attack_penalty,
    calculate_unused_attack_penalty,
)
from app.models.enums import ViolationCode, WarType
from app.models import ClanMembershipHistory
from app.domain.violation_rules import evaluate_attack_violation
from app.repositories.stats import StatsRepository
from app.utils.time import utcnow


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(slots=True)
class ContributionRankingRow:
    player_tag: str
    player_name: str
    wars: int
    score: float
    newcomer: bool


class ContributionDataUnavailableError(Exception):
    """Raised when contribution ranking cannot be built due to missing cycle data."""


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
        joined_at = _normalize_utc(membership.joined_at)
        return (_normalize_utc(utcnow()) - joined_at) < timedelta(days=15)

    async def build_contribution_ranking(self, period: Any) -> list[ContributionRankingRow]:
        stats_rows = await self.repo.aggregated_player_stats(clan_tag=self.config.main_clan_tag, period_start=period.start, period_end=period.end)
        if not stats_rows:
            raise ContributionDataUnavailableError("⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет игроков в основном клане.")
        attacks_rows = await self.repo.attack_rows_for_players(self.config.main_clan_tag, period.start, period.end, [r.player_tag for r in stats_rows])
        if not attacks_rows:
            raise ContributionDataUnavailableError("⚠️ Общий вклад пока пуст: в текущем цикле еще никто не сделал атак.")
        by_tag: dict[str, float] = {r.player_tag: 0.0 for r in stats_rows}
        attacks_by_war_tag: dict[tuple[int, str], int] = defaultdict(int)
        attacked_by_war: dict[int, set[int]] = defaultdict(set)
        for attack, war, _violation in attacks_rows:
            attacks_by_war_tag[(war.id, attack.attacker_tag)] += 1
            attacked_by_war[war.id].add(attack.defender_position)
            is_cwl = war.war_type.value == "cwl"
            decision = None if is_cwl else evaluate_attack_violation(
                war_start_time=war.start_time,
                attack_seen_at=attack.observed_at,
                attacker_position=attack.attacker_position,
                defender_position=attack.defender_position,
            )
            is_above_self_violation = bool(decision and decision.code == ViolationCode.ABOVE_SELF)
            is_too_low_violation = bool(decision and decision.code == ViolationCode.TOO_LOW)
            by_tag[attack.attacker_tag] += calculate_attack_contribution(
                ContributionAttackInput(
                    stars=attack.stars,
                    destruction=attack.destruction,
                    attacker_position=attack.attacker_position,
                    defender_position=attack.defender_position,
                    is_cwl=is_cwl,
                    is_above_self_violation=is_above_self_violation,
                    is_too_low_violation=is_too_low_violation,
                )
            ).score

        participation_rows = await self.repo.participation_rows_for_players(self.config.main_clan_tag, period.start, period.end, [r.player_tag for r in stats_rows])
        war_ids = list({war.id for _, war in participation_rows})
        enemy_rows = await self.repo.enemy_participation_rows_for_wars(war_ids)
        opponent_positions_by_war: dict[int, list[int]] = defaultdict(list)
        for enemy in enemy_rows:
            opponent_positions_by_war[enemy.war_id].append(enemy.map_position)

        for participant, war in participation_rows:
            used = attacks_by_war_tag.get((war.id, participant.player_tag), 0)
            if war.war_type == WarType.CWL:
                by_tag[participant.player_tag] += calculate_cwl_unused_attack_penalty(
                    unused_attack=used == 0,
                    opponent_positions=opponent_positions_by_war.get(war.id, []),
                    attacked_defender_positions=list(attacked_by_war.get(war.id, set())),
                )
                continue

            by_tag[participant.player_tag] += calculate_unused_attack_penalty(
                is_cwl=False,
                unused_attacks=max(0, 2 - used),
                attacker_position=participant.map_position,
                opponent_positions=opponent_positions_by_war.get(war.id, []),
                attacked_defender_positions=list(attacked_by_war.get(war.id, set())),
            )
        ranking: list[ContributionRankingRow] = []
        for row in stats_rows:
            newcomer = await self.is_newcomer(row.player_id, round(by_tag.get(row.player_tag, 0.0), 2), row.wars) if hasattr(row, "player_id") else False
            ranking.append(ContributionRankingRow(row.player_tag, row.player_name, row.wars, round(by_tag.get(row.player_tag, 0.0), 2), newcomer))
        return sorted(ranking, key=lambda x: (-x.score, x.player_name.casefold(), x.player_tag))

    def format_contribution_ranking(self, ranking: list[ContributionRankingRow]) -> str:
        if not ranking:
            raise ContributionDataUnavailableError("⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет данных по атакам.")
        lines = ["🏆 Общий вклад", ""]
        for idx, row in enumerate(ranking, 1):
            suffix = " 🆕 новенький" if row.newcomer else ""
            lines.append(f"{idx}. {row.player_name} — {row.score:.2f}{suffix}")
        return "\n".join(lines)
