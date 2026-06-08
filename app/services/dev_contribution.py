from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
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
from app.services.active_violation_counter import ActiveViolationCounterService
from app.services.donations import DonationService
from app.utils.time import utcnow


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _select_best_attack_result(attacks: list[tuple[int, float]]) -> tuple[int, float]:
    if not attacks:
        return 0, 0.0
    return max(attacks, key=lambda attack_result: (attack_result[0], attack_result[1]))


@dataclass(slots=True)
class ContributionRankingRow:
    player_tag: str
    player_name: str
    wars: int
    score: float
    newcomer: bool
    active_violations: int = 0
    donations: int = 0


class ContributionDataUnavailableError(Exception):
    """Raised when contribution ranking cannot be built due to missing cycle data."""


class DevContributionService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = StatsRepository(session)
        self.active_violation_counter = ActiveViolationCounterService(session)

    async def get_total_membership_duration(self, player_id: int) -> timedelta | None:
        now_utc = _normalize_utc(utcnow())
        membership_query: Select[tuple[ClanMembershipHistory]] = (
            select(ClanMembershipHistory)
            .where(
                ClanMembershipHistory.player_id == player_id,
                ClanMembershipHistory.clan_tag == self.config.main_clan_tag,
            )
            .order_by(ClanMembershipHistory.joined_at.asc())
        )
        rows = await self.session.scalars(membership_query)
        history = list(rows)
        if history:
            total = timedelta(0)
            for membership in history:
                joined_at = membership.joined_at
                if joined_at is None:
                    continue
                joined_at_utc = _normalize_utc(joined_at)
                left_at = membership.left_at
                end_at_utc = now_utc if left_at is None else _normalize_utc(left_at)
                if end_at_utc <= joined_at_utc:
                    continue
                total += end_at_utc - joined_at_utc
            return total

        fallback_membership = await self.session.scalar(
            select(ClanMembershipHistory)
            .where(
                ClanMembershipHistory.player_id == player_id,
                ClanMembershipHistory.clan_tag == self.config.main_clan_tag,
                ClanMembershipHistory.left_at.is_(None),
            )
            .order_by(ClanMembershipHistory.joined_at.desc())
        )
        if fallback_membership is None or fallback_membership.joined_at is None:
            return None
        return max(timedelta(0), now_utc - _normalize_utc(fallback_membership.joined_at))

    async def is_newcomer(self, player_id: int) -> bool:
        total_duration = await self.get_total_membership_duration(player_id)
        if total_duration is None:
            return False
        return total_duration < timedelta(days=7)

    async def build_contribution_ranking(self, period: Any) -> list[ContributionRankingRow]:
        stats_rows = await self.repo.aggregated_player_stats(clan_tag=self.config.main_clan_tag, period_start=period.start, period_end=period.end)
        if not stats_rows:
            raise ContributionDataUnavailableError("⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет игроков в основном клане.")
        donation_service = DonationService(self.session, self.config)
        attacks_rows = await self.repo.attack_rows_for_players(self.config.main_clan_tag, period.start, period.end, [r.player_tag for r in stats_rows])
        if not attacks_rows:
            raise ContributionDataUnavailableError("⚠️ Общий вклад пока пуст: в текущем цикле еще никто не сделал атак.")
        by_tag: dict[str, float] = {r.player_tag: 0.0 for r in stats_rows}
        attacks_by_war_tag: dict[tuple[int, str], int] = defaultdict(int)
        attacked_by_war: dict[int, set[int]] = defaultdict(set)
        sorted_attacks_rows = sorted(
            attacks_rows,
            key=lambda row: (
                row[1].id,
                _normalize_utc(row[0].observed_at),
                row[0].attacker_tag,
                row[0].defender_position,
            ),
        )
        previous_attacks_by_target: dict[tuple[int, int], list[tuple[int, float]]] = defaultdict(list)

        for attack, war, _violation in sorted_attacks_rows:
            attacks_by_war_tag[(war.id, attack.attacker_tag)] += 1
            attacked_by_war[war.id].add(attack.defender_position)
            target_key = (war.id, attack.defender_position)
            if _violation is not None and _violation.code == ViolationCode.CLAIMED_TARGET:
                by_tag[attack.attacker_tag] += -50.0
                previous_attacks_by_target[target_key].append((attack.stars, attack.destruction))
                continue
            is_cwl = war.war_type.value == "cwl"
            decision = None if is_cwl else evaluate_attack_violation(
                war_start_time=war.start_time,
                attack_seen_at=attack.observed_at,
                attacker_position=attack.attacker_position,
                defender_position=attack.defender_position,
            )
            is_above_self_violation = bool(decision and decision.code == ViolationCode.ABOVE_SELF)
            is_too_low_violation = bool(decision and decision.code == ViolationCode.TOO_LOW)
            previous_attacks = previous_attacks_by_target[target_key]
            prev_best_stars, prev_best_destruction = _select_best_attack_result(previous_attacks)
            target_already_attacked = bool(previous_attacks)

            by_tag[attack.attacker_tag] += calculate_attack_contribution(
                ContributionAttackInput(
                    stars=attack.stars,
                    destruction=attack.destruction,
                    attacker_position=attack.attacker_position,
                    defender_position=attack.defender_position,
                    is_cwl=is_cwl,
                    previous_best_stars=prev_best_stars,
                    previous_best_destruction=prev_best_destruction,
                    target_already_attacked=target_already_attacked,
                    is_above_self_violation=is_above_self_violation,
                    is_too_low_violation=is_too_low_violation,
                )
            ).score

            previous_attacks_by_target[target_key].append((attack.stars, attack.destruction))

        participation_rows = await self.repo.participation_rows_for_players(self.config.main_clan_tag, period.start, period.end, [r.player_tag for r in stats_rows])
        war_ids = list({war.id for _, war in participation_rows})
        enemy_rows = await self.repo.enemy_participation_rows_for_wars(war_ids)
        opponent_positions_by_war: dict[int, list[int]] = defaultdict(list)
        for enemy in enemy_rows:
            opponent_positions_by_war[enemy.war_id].append(enemy.map_position)

        now_utc = _normalize_utc(utcnow())
        for participant, war in participation_rows:
            used = attacks_by_war_tag.get((war.id, participant.player_tag), 0)
            war_end_utc = _normalize_utc(war.end_time)
            war_finished = now_utc >= war_end_utc

            if war.war_type == WarType.CWL:
                if not war_finished:
                    continue
                by_tag[participant.player_tag] += calculate_cwl_unused_attack_penalty(
                    unused_attack=used == 0,
                    opponent_positions=opponent_positions_by_war.get(war.id, []),
                    attacked_defender_positions=list(attacked_by_war.get(war.id, set())),
                )
                continue

            if not war_finished:
                continue

            by_tag[participant.player_tag] += calculate_unused_attack_penalty(
                is_cwl=False,
                unused_attacks=max(0, 2 - used),
                attacker_position=participant.map_position,
                opponent_positions=opponent_positions_by_war.get(war.id, []),
                attacked_defender_positions=list(attacked_by_war.get(war.id, set())),
            )
        active_counts = await self.active_violation_counter.counts_for_players(
            [row.player_tag for row in stats_rows], period.start, period.end
        )
        ranking: list[ContributionRankingRow] = []
        for row in stats_rows:
            newcomer = await self.is_newcomer(row.player_id) if hasattr(row, "player_id") else False
            donations_score = await donation_service.calculate_player_donations_for_period(
                row.player_tag, period.start, period.end
            )
            ranking.append(
                ContributionRankingRow(
                    player_tag=row.player_tag,
                    player_name=row.player_name,
                    wars=row.wars,
                    score=round(by_tag.get(row.player_tag, 0.0) + donations_score, 2),
                    newcomer=newcomer,
                    active_violations=active_counts.get(row.player_tag, 0),
                    donations=donations_score,
                )
            )
        return sorted(ranking, key=lambda x: (-x.score, x.player_name.casefold(), x.player_tag))

    def format_contribution_ranking(self, ranking: list[ContributionRankingRow]) -> str:
        if not ranking:
            raise ContributionDataUnavailableError("⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет данных по атакам.")
        lines = ["🏆 Общий вклад", ""]
        for idx, row in enumerate(ranking, 1):
            violation_suffix = " ❌" if row.active_violations >= 3 else ""
            newcomer_suffix = " 🆕 новенький" if row.newcomer else ""
            lines.append(
                f"{idx}. {row.player_name} — {row.score:.2f} | донат: {row.donations}{violation_suffix}{newcomer_suffix}"
            )
        return "\n".join(lines)
