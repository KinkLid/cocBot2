from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.models import Violation
from app.models.enums import ViolationCode, WarType
from app.repositories.stats import StatsRepository
from app.repositories.war import WarRepository
from app.services.period import PeriodService


@dataclass(slots=True)
class ManualViolationPlayerOption:
    player_tag: str
    player_name: str
    current_clan_rank: int | None
    attacks_count: int


class ManualViolationService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.period_service = PeriodService(session)
        self.stats_repo = StatsRepository(session)
        self.wars = WarRepository(session)

    async def list_players_with_attacks_for_current_cycle(self) -> list[ManualViolationPlayerOption]:
        period = await self.period_service.current_cycle()
        stats = await self.stats_repo.aggregated_player_stats(
            clan_tag=self.config.main_clan_tag,
            period_start=period.start,
            period_end=period.end,
        )
        rows = [ManualViolationPlayerOption(r.player_tag, r.player_name, r.clan_rank, r.attacks) for r in stats if r.attacks > 0]
        return sorted(rows, key=lambda x: (x.current_clan_rank is None, x.current_clan_rank or 999, x.player_name.casefold()))

    def format_players_for_selection(self, players: list[ManualViolationPlayerOption]) -> str:
        lines = ["🚩 Чужой флажок", "Выберите игрока по номеру.", ""]
        for idx, player in enumerate(players, 1):
            lines.append(f"{idx}. {player.player_name} — атак: {player.attacks_count}")
        lines.append("")
        lines.append("⬅️ Назад")
        return "\n".join(lines)

    async def list_player_attacks_for_current_cycle(self, player_tag: str):
        period = await self.period_service.current_cycle()
        return await self.wars.list_attacks_for_player_in_period(self.config.main_clan_tag, player_tag, period.start, period.end)

    def format_attacks_for_selection(self, player_name: str, attacks) -> str:
        lines = ["🚩 Чужой флажок", f"Игрок: {player_name}", "Выберите атаку по номеру.", ""]
        for idx, (attack, war, violation) in enumerate(attacks, 1):
            war_label = "ЛВК" if war.war_type == WarType.CWL else "КВ"
            suffix = f" [нарушение: {violation.code.value}]" if violation is not None else ""
            lines.append(
                f"{idx}. {attack.observed_at:%Y-%m-%d %H:%M} | {war_label} | {attack.attacker_position} -> {attack.defender_position} | {attack.stars}⭐ {int(attack.destruction)}%{suffix}"
            )
        lines.append("")
        lines.append("⬅️ Назад")
        return "\n".join(lines)

    async def apply_claimed_target_violation(self, attack_id: int, admin_telegram_id: int) -> str:
        attack = await self.wars.get_attack_by_id(attack_id)
        if attack is None:
            raise ValueError("Атака не найдена")
        violation = await self.wars.get_violation_by_attack_id(attack.id)
        if violation is None:
            violation = await self.wars.add_violation(
                Violation(
                    attack_id=attack.id,
                    war_id=attack.war_id,
                    player_tag=attack.attacker_tag,
                    code=ViolationCode.CLAIMED_TARGET,
                    reason_text="Атака по чужому флажку",
                    player_position=attack.attacker_position,
                    target_position=attack.defender_position,
                    detected_at=attack.observed_at,
                    is_manual=True,
                )
            )
        else:
            violation.code = ViolationCode.CLAIMED_TARGET
            violation.reason_text = "Атака по чужому флажку"
            violation.player_tag = attack.attacker_tag
            violation.war_id = attack.war_id
            violation.player_position = attack.attacker_position
            violation.target_position = attack.defender_position
            violation.detected_at = attack.observed_at
            violation.is_manual = True
            await self.session.flush()
        _ = admin_telegram_id
        return (
            "✅ Нарушение поставлено\n"
            f"Игрок: {attack.attacker_name}\n"
            f"Цель: {attack.defender_name}\n"
            f"Атака: {attack.stars}⭐ {int(attack.destruction)}%\n"
            "Теперь эта атака дает -50.00 к общему вкладу."
        )
