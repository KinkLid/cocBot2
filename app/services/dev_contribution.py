from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig

from app.domain.dev_contribution import (
    ContributionAttackInput,
    calculate_attack_contribution,
    calculate_cwl_unused_attack_penalty,
    calculate_unused_attack_penalty,
)
from app.models.enums import ViolationCode, WarType
from app.models import ClanMembershipHistory
from app.repositories.stats import StatsRepository
from app.repositories.manual_contribution import ManualContributionRepository
from app.services.active_violation_counter import ActiveViolationCounterService
from app.services.donations import DonationService
from app.utils.time import utcnow


DONATION_POINTS_PER_UNIT = 0.01


def _calculate_donation_points(raw_donations: int) -> float:
    return round(raw_donations * DONATION_POINTS_PER_UNIT, 2)


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
    donation_points: float = 0.0
    manual_adjustment: int = 0


@dataclass(slots=True)
class ContributionScoreComponent:
    kind: str
    player_tag: str
    score_delta: float
    attack: Any | None = None
    war: Any | None = None
    violation_code: ViolationCode | None = None
    manual_adjustment: Any | None = None


@dataclass(slots=True)
class ContributionCalculation:
    stats_rows: list[Any]
    components_by_tag: dict[str, list[ContributionScoreComponent]] = field(default_factory=dict)
    active_violations_by_tag: dict[str, int] = field(default_factory=dict)
    donations_by_tag: dict[str, int] = field(default_factory=dict)

    def score_for(self, player_tag: str) -> float:
        return round(sum(item.score_delta for item in self.components_by_tag.get(player_tag, [])), 2)


class ContributionDataUnavailableError(Exception):
    """Raised when contribution ranking cannot be built due to missing cycle data."""


class DevContributionService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = StatsRepository(session)
        self.active_violation_counter = ActiveViolationCounterService(session)

    async def get_total_membership_duration(
        self,
        player_id: int,
        as_of: datetime | None = None,
    ) -> timedelta | None:
        now_utc = _normalize_utc(utcnow() if as_of is None else as_of)
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
                if joined_at_utc > now_utc:
                    continue
                left_at = membership.left_at
                end_at_utc = now_utc if left_at is None else min(_normalize_utc(left_at), now_utc)
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

    async def is_newcomer(
        self,
        player_id: int,
        as_of: datetime | None = None,
    ) -> bool:
        total_duration = await self.get_total_membership_duration(player_id, as_of)
        if total_duration is None:
            return False
        return total_duration < timedelta(days=7)

    async def build_contribution_calculation(
        self,
        period: Any,
        *,
        require_attacks: bool = True,
        include_historical_members: bool = False,
    ) -> ContributionCalculation:
        stats_rows = await self.repo.aggregated_player_stats(
            clan_tag=self.config.main_clan_tag,
            period_start=period.start,
            period_end=period.end,
            include_historical_members=include_historical_members,
        )
        if not stats_rows:
            raise ContributionDataUnavailableError(
                "⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет игроков в основном клане."
            )

        player_tags = [row.player_tag for row in stats_rows]
        player_id_by_tag = {row.player_tag: row.player_id for row in stats_rows}
        manual_repo = ManualContributionRepository(self.session)
        manual_totals = await manual_repo.manual_adjustment_totals(
            list(player_id_by_tag.values()), self.config.main_clan_tag, period.start, period.end
        )
        attacks_rows = await self.repo.attack_rows_for_players(
            self.config.main_clan_tag, period.start, period.end, player_tags
        )
        if require_attacks and not attacks_rows and not manual_totals:
            raise ContributionDataUnavailableError(
                "⚠️ Общий вклад пока пуст: в текущем цикле еще никто не сделал атак."
            )

        components_by_tag: dict[str, list[ContributionScoreComponent]] = {tag: [] for tag in player_tags}
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

        for attack, war, stored_violation in sorted_attacks_rows:
            attacks_by_war_tag[(war.id, attack.attacker_tag)] += 1
            attacked_by_war[war.id].add(attack.defender_position)
            target_key = (war.id, attack.defender_position)
            if stored_violation is not None and stored_violation.code == ViolationCode.CLAIMED_TARGET:
                components_by_tag.setdefault(attack.attacker_tag, []).append(
                    ContributionScoreComponent(
                        kind="attack",
                        player_tag=attack.attacker_tag,
                        score_delta=-50.0,
                        attack=attack,
                        war=war,
                        violation_code=stored_violation.code,
                    )
                )
                previous_attacks_by_target[target_key].append((attack.stars, attack.destruction))
                continue

            is_cwl = war.war_type == WarType.CWL
            automatic_violation_code = None
            if not is_cwl and stored_violation is not None:
                if stored_violation.code in {
                    ViolationCode.ABOVE_SELF,
                    ViolationCode.TOO_LOW,
                }:
                    automatic_violation_code = stored_violation.code

            is_above_self_violation = (
                automatic_violation_code == ViolationCode.ABOVE_SELF
            )
            is_too_low_violation = (
                automatic_violation_code == ViolationCode.TOO_LOW
            )
            previous_attacks = previous_attacks_by_target[target_key]
            prev_best_stars, prev_best_destruction = _select_best_attack_result(previous_attacks)
            contribution = calculate_attack_contribution(
                ContributionAttackInput(
                    stars=attack.stars,
                    destruction=attack.destruction,
                    attacker_position=attack.attacker_position,
                    defender_position=attack.defender_position,
                    is_cwl=is_cwl,
                    previous_best_stars=prev_best_stars,
                    previous_best_destruction=prev_best_destruction,
                    target_already_attacked=bool(previous_attacks),
                    is_above_self_violation=is_above_self_violation,
                    is_too_low_violation=is_too_low_violation,
                )
            )
            components_by_tag.setdefault(attack.attacker_tag, []).append(
                ContributionScoreComponent(
                    kind="attack",
                    player_tag=attack.attacker_tag,
                    score_delta=contribution.score,
                    attack=attack,
                    war=war,
                    violation_code=automatic_violation_code,
                )
            )
            previous_attacks_by_target[target_key].append((attack.stars, attack.destruction))

        participation_rows = await self.repo.participation_rows_for_players(
            self.config.main_clan_tag, period.start, period.end, player_tags
        )
        war_ids = list({war.id for _, war in participation_rows})
        enemy_rows = await self.repo.enemy_participation_rows_for_wars(war_ids)
        opponent_positions_by_war: dict[int, list[int]] = defaultdict(list)
        for enemy in enemy_rows:
            opponent_positions_by_war[enemy.war_id].append(enemy.map_position)

        now_utc = _normalize_utc(utcnow())
        for participant, war in participation_rows:
            used = attacks_by_war_tag.get((war.id, participant.player_tag), 0)
            if now_utc < _normalize_utc(war.end_time):
                continue
            if war.war_type == WarType.CWL:
                penalty = calculate_cwl_unused_attack_penalty(
                    unused_attack=used == 0,
                    opponent_positions=opponent_positions_by_war.get(war.id, []),
                    attacked_defender_positions=list(attacked_by_war.get(war.id, set())),
                )
            else:
                penalty = calculate_unused_attack_penalty(
                    is_cwl=False,
                    unused_attacks=max(0, 2 - used),
                    attacker_position=participant.map_position,
                    opponent_positions=opponent_positions_by_war.get(war.id, []),
                    attacked_defender_positions=list(attacked_by_war.get(war.id, set())),
                )
            if penalty:
                components_by_tag.setdefault(participant.player_tag, []).append(
                    ContributionScoreComponent(
                        kind="unused_attack_penalty",
                        player_tag=participant.player_tag,
                        score_delta=penalty,
                        war=war,
                    )
                )

        active_counts = await self.active_violation_counter.counts_for_players(
            player_tags, period.start, period.end
        )
        donation_service = DonationService(self.session, self.config)
        donations_by_tag: dict[str, int] = {}
        for row in stats_rows:
            donations = await donation_service.calculate_player_donations_for_period(
                row.player_tag, period.start, period.end
            )
            donations_by_tag[row.player_tag] = donations
            donation_points = _calculate_donation_points(donations)
            components_by_tag[row.player_tag].append(
                ContributionScoreComponent(
                    kind="donations",
                    player_tag=row.player_tag,
                    score_delta=donation_points,
                )
            )

        for tag, player_id in player_id_by_tag.items():
            points = manual_totals.get(player_id, 0)
            if points:
                components_by_tag[tag].append(
                    ContributionScoreComponent(
                        kind="manual_adjustment",
                        player_tag=tag,
                        score_delta=float(points),
                    )
                )

        return ContributionCalculation(
            stats_rows=list(stats_rows),
            components_by_tag=components_by_tag,
            active_violations_by_tag=active_counts,
            donations_by_tag=donations_by_tag,
        )

    async def build_contribution_ranking(
        self,
        period: Any,
        *,
        include_historical_members: bool = False,
    ) -> list[ContributionRankingRow]:
        calculation = await self.build_contribution_calculation(
            period,
            include_historical_members=include_historical_members,
        )
        ranking: list[ContributionRankingRow] = []
        for row in calculation.stats_rows:
            newcomer = (
                await self.is_newcomer(row.player_id, as_of=period.end)
                if hasattr(row, "player_id")
                else False
            )
            ranking.append(
                ContributionRankingRow(
                    player_tag=row.player_tag,
                    player_name=row.player_name,
                    wars=row.wars,
                    score=calculation.score_for(row.player_tag),
                    newcomer=newcomer,
                    active_violations=calculation.active_violations_by_tag.get(row.player_tag, 0),
                    donations=calculation.donations_by_tag.get(row.player_tag, 0),
                    donation_points=_calculate_donation_points(
                        calculation.donations_by_tag.get(row.player_tag, 0)
                    ),
                    manual_adjustment=int(sum(c.score_delta for c in calculation.components_by_tag.get(row.player_tag, []) if c.kind == "manual_adjustment")),
                )
            )
        return sorted(ranking, key=lambda x: (-x.score, x.player_name.casefold(), x.player_tag))

    def format_contribution_ranking(
        self,
        ranking: list[ContributionRankingRow],
        *,
        title: str = "🏆 Общий вклад",
        period: Any | None = None,
    ) -> str:
        if not ranking:
            raise ContributionDataUnavailableError("⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет данных по атакам.")
        lines = [title]
        if period is not None:
            lines.append(f"📅 {period.start:%d.%m.%Y} — {period.end:%d.%m.%Y}")
        lines.append("")
        for idx, row in enumerate(ranking, 1):
            violation_suffix = " ❌" if row.active_violations >= 3 else ""
            newcomer_suffix = " 🆕 новенький" if row.newcomer else ""
            lines.append(
                f"{idx}. {row.player_name} — {row.score:.2f}"
                f"{violation_suffix}{newcomer_suffix}"
            )
        return "\n".join(lines)
