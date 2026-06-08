from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.models.enums import WarType
from app.services.dev_contribution import ContributionScoreComponent, DevContributionService


@dataclass(slots=True)
class ContributionBreakdownItem:
    kind: str
    title: str
    occurred_at: datetime | None
    score_delta: float
    details: str | None = None


@dataclass(slots=True)
class PlayerContributionBreakdown:
    player_tag: str
    player_name: str
    period_start: datetime
    period_end: datetime
    attack_score_total: float
    unused_attack_penalty_total: float
    donation_total: int
    donation_score_total: float
    final_score: float
    active_violations: int
    items: list[ContributionBreakdownItem]


class ContributionBreakdownService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.contribution_service = DevContributionService(session, config)

    async def build_player_breakdown(self, player_tag: str, period: Any) -> PlayerContributionBreakdown:
        calculation = await self.contribution_service.build_contribution_calculation(
            period, require_attacks=False
        )
        stats_row = next((row for row in calculation.stats_rows if row.player_tag == player_tag), None)
        player_name = stats_row.player_name if stats_row is not None else player_tag
        components = calculation.components_by_tag.get(player_tag, [])
        donation_total = calculation.donations_by_tag.get(player_tag, 0)
        items = [self._build_item(component, donation_total) for component in components]
        attack_total = sum(item.score_delta for item in items if item.kind == "attack")
        penalty_total = sum(
            item.score_delta for item in items if item.kind == "unused_attack_penalty"
        )
        donation_score_total = sum(
            item.score_delta for item in items if item.kind == "donations"
        )
        final_score = round(sum(item.score_delta for item in items), 2)
        return PlayerContributionBreakdown(
            player_tag=player_tag,
            player_name=player_name,
            period_start=period.start,
            period_end=period.end,
            attack_score_total=round(attack_total, 2),
            unused_attack_penalty_total=round(penalty_total, 2),
            donation_total=donation_total,
            donation_score_total=round(donation_score_total, 2),
            final_score=final_score,
            active_violations=calculation.active_violations_by_tag.get(player_tag, 0),
            items=items,
        )

    @staticmethod
    def _war_label(war: Any) -> str:
        return "ЛВК" if war.war_type == WarType.CWL else "КВ"

    def _build_item(
        self, component: ContributionScoreComponent, donation_total: int
    ) -> ContributionBreakdownItem:
        if component.kind == "donations":
            return ContributionBreakdownItem(
                kind="donations",
                title="Донаты войск за цикл",
                occurred_at=None,
                score_delta=component.score_delta,
                details=f"Сырой донат: {donation_total}",
            )
        if component.kind == "unused_attack_penalty":
            war_date = component.war.end_time.strftime("%Y-%m-%d")
            return ContributionBreakdownItem(
                kind=component.kind,
                title="Штраф за неиспользованную атаку",
                occurred_at=component.war.end_time,
                score_delta=component.score_delta,
                details=f"{self._war_label(component.war)} {war_date}",
            )

        attack = component.attack
        details = (
            f"{self._war_label(component.war)} | "
            f"{attack.attacker_position} -> {attack.defender_position} | "
            f"{attack.stars}⭐ {attack.destruction:g}%"
        )
        if component.violation_code is not None:
            details += f" | Нарушение: {component.violation_code.value}"
        return ContributionBreakdownItem(
            kind="attack",
            title="Атака",
            occurred_at=attack.observed_at,
            score_delta=component.score_delta,
            details=details,
        )

    @staticmethod
    def format_short_breakdown(breakdown: PlayerContributionBreakdown) -> str:
        return "\n".join(
            [
                "📋 Мой вклад",
                f"Период: {breakdown.period_start:%Y-%m-%d} — {breakdown.period_end:%Y-%m-%d}",
                "",
                f"Атаки: {breakdown.attack_score_total:+.2f}",
                f"Неиспользованные атаки: {breakdown.unused_attack_penalty_total:+.2f}",
                f"Донаты: {breakdown.donation_score_total:+.2f} "
                f"(сырой донат: {breakdown.donation_total})",
                f"Активные нарушения: {breakdown.active_violations}",
                "",
                f"Итого: {breakdown.final_score:.2f}",
            ]
        )

    @staticmethod
    def format_detailed_breakdown(breakdown: PlayerContributionBreakdown) -> str:
        lines = [
            f"🧾 Разбор вклада: {breakdown.player_name}",
            f"Период: {breakdown.period_start:%Y-%m-%d} — {breakdown.period_end:%Y-%m-%d}",
            f"Активные нарушения: {breakdown.active_violations}",
            "",
        ]
        for index, item in enumerate(breakdown.items, 1):
            if item.occurred_at is not None and item.kind == "attack":
                heading = f"{item.occurred_at:%Y-%m-%d %H:%M} | {item.details}"
            elif item.details:
                heading = f"{item.title} | {item.details}"
            else:
                heading = item.title
            lines.extend([f"{index}. {heading}", f"{item.score_delta:+.2f}", ""])
        if not breakdown.items:
            lines.extend(["Нет начислений за текущий цикл.", ""])
        lines.append(f"Итого: {breakdown.final_score:.2f}")
        return "\n".join(lines)
