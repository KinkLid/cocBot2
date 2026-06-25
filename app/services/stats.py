from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.models.enums import ViolationCode, WarType
from app.repositories.capital_raid_violation import CapitalRaidViolationRepository
from app.repositories.stats import StatsRepository
from app.repositories.war import WarRepository
from app.schemas.dto import PlayerStatsDTO
from app.services.active_violation_counter import ActiveViolationCounterService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FormattedStats:
    text: str
    rows: list[PlayerStatsDTO]


class StatsService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = StatsRepository(session)
        self.war_repo = WarRepository(session)
        self.capital_violation_repo = CapitalRaidViolationRepository(session)
        self.active_violation_counter = ActiveViolationCounterService(session)

    async def player_stats(self, period_start, period_end, player_tag: str) -> PlayerStatsDTO:
        rows = await self.repo.aggregated_player_stats(
            clan_tag=self.config.main_clan_tag,
            period_start=period_start,
            period_end=period_end,
            player_tags=[player_tag],
        )
        contribution_place = await self.player_contribution_place(period_start, period_end, player_tag)
        if not rows:
            raise ValueError("Игрок сейчас не состоит в клане или отсутствуют данные")
        row = rows[0]
        return PlayerStatsDTO(
            player_tag=row.player_tag,
            player_name=row.player_name,
            town_hall=row.town_hall,
            telegram_id=row.telegram_id,
            telegram_username=row.telegram_username,
            registered_at=row.registered_at,
            wars=row.wars,
            attacks=row.attacks,
            stars=row.stars,
            violations=await self.active_violation_counter.count_for_player(row.player_tag, period_start, period_end),
            place=contribution_place,
            clan_rank=row.clan_rank,
        )


    async def player_contribution_place(self, period_start, period_end, player_tag: str) -> int:
        from app.services.dev_contribution import ContributionDataUnavailableError, DevContributionService

        try:
            ranking = await DevContributionService(self.session, self.config).build_contribution_ranking(SimpleNamespace(start=period_start, end=period_end))
        except (ContributionDataUnavailableError, ValueError, TypeError):
            logger.exception("Failed to build contribution ranking for player stats")
            return 0
        except Exception:
            logger.exception("Unexpected error while building contribution ranking for player stats")
            return 0

        for idx, row in enumerate(ranking, 1):
            if row.player_tag == player_tag:
                return idx
        return 0

    async def clan_stats(self, period_start, period_end, sort_by: str = "clan_order") -> FormattedStats:
        rows = await self.repo.aggregated_player_stats(
            clan_tag=self.config.main_clan_tag,
            period_start=period_start,
            period_end=period_end,
        )
        sorted_rows = list(rows)
        ranking_source = sorted(rows, key=lambda item: (-item.stars, item.clan_rank or 10_000, item.player_name))
        places = {row.player_tag: idx + 1 for idx, row in enumerate(ranking_source)}

        if sort_by == "stars":
            sorted_rows = ranking_source
        elif sort_by == "place":
            sorted_rows = sorted(ranking_source, key=lambda item: places[item.player_tag])
        else:
            sorted_rows = sorted(rows, key=lambda item: (item.clan_rank or 10_000, item.player_name))

        active_counts = await self.active_violation_counter.counts_for_players(
            [row.player_tag for row in sorted_rows], period_start, period_end
        )
        dto_rows = [
            PlayerStatsDTO(
                player_tag=row.player_tag,
                player_name=row.player_name,
                town_hall=row.town_hall,
                telegram_id=row.telegram_id,
                telegram_username=row.telegram_username,
                registered_at=row.registered_at,
                wars=row.wars,
                attacks=row.attacks,
                stars=row.stars,
                violations=active_counts.get(row.player_tag, 0),
                place=places[row.player_tag],
                clan_rank=row.clan_rank,
            )
            for row in sorted_rows
        ]
        text = "\n\n".join(self.format_player_card(row, period_start.date().isoformat(), period_end.date().isoformat()) for row in dto_rows)
        return FormattedStats(text=text, rows=dto_rows)

    def format_compact_players_by_clan_order(self, rows: list[PlayerStatsDTO]) -> str:
        return "\n".join(f"{idx}. {row.player_name}" for idx, row in enumerate(rows, 1))

    def format_compact_players_by_stars(self, rows: list[PlayerStatsDTO]) -> str:
        return "\n".join(f"{idx}. {row.player_name} — {row.stars} ⭐" for idx, row in enumerate(rows, 1))

    def format_compact_players_by_place(self, rows: list[PlayerStatsDTO]) -> str:
        ordered = sorted(rows, key=lambda r: r.place)
        return "\n".join(f"{idx}. {row.player_name}" for idx, row in enumerate(ordered, 1))

    def format_player_card(self, row: PlayerStatsDTO, period_start: str, period_end: str) -> str:
        tg_line = (
            f"└ 👤 @{row.telegram_username} • 🆔 {row.telegram_id} • 🗓 {row.registered_at:%Y-%m-%d %H:%M}"
            if row.telegram_id and row.registered_at
            else "└ 👤 Не привязан к Telegram"
        )
        parts = [
            f"👤 {row.player_name} {row.player_tag}",
            tg_line,
            "",
            f"📆 Период: {period_start} — {period_end}",
            f"⚔️ Войн: {row.wars}",
            f"🗡 Атак: {row.attacks}",
            f"⭐ Звёзд: {row.stars}",
        ]
        parts.append(f"⚠️ Активных нарушений: {row.violations}")
        parts.append(f"🏅 Место в клане: {row.place}")
        return "\n".join(parts)


    async def violations_ranking_current_cycle_data(self, period_start, period_end) -> list[dict[str, int | str]]:
        rows = await self.repo.current_clan_members_violations(
            clan_tag=self.config.main_clan_tag,
            period_start=period_start,
            period_end=period_end,
        )
        player_tags = [player_tag for player_tag, _, _, violations in rows if violations > 0]
        active_counts = await self.active_violation_counter.counts_for_players(
            player_tags, period_start, period_end
        )
        ranked = sorted(
            (
                (player_tag, player_name, clan_rank, violations, active_counts.get(player_tag, 0))
                for player_tag, player_name, clan_rank, violations in rows
                if violations > 0
            ),
            key=lambda row: (
                -row[3],
                -row[4],
                row[2] or 10_000,
                row[1],
            ),
        )
        return [
            {
                "player_tag": player_tag,
                "player_name": player_name,
                "violations": violations,
                "active_violations": active_violations,
            }
            for player_tag, player_name, _, violations, active_violations in ranked
        ]

    async def violation_counter_reset_options(
        self, period_start, period_end
    ) -> list[dict[str, int | str]]:
        rows = await self.repo.current_clan_members_violations(
            clan_tag=self.config.main_clan_tag,
            period_start=period_start,
            period_end=period_end,
        )
        active_counts = await self.active_violation_counter.counts_for_players(
            [player_tag for player_tag, _, _, _ in rows], period_start, period_end
        )
        ordered = sorted(
            (
                (player_tag, player_name, clan_rank, active_counts.get(player_tag, 0))
                for player_tag, player_name, clan_rank, _ in rows
            ),
            key=lambda row: (-row[3], row[2] or 10_000, row[1]),
        )
        return [
            {"player_tag": player_tag, "player_name": player_name, "violations": violations}
            for player_tag, player_name, _, violations in ordered
            if violations > 0
        ]

    def format_violation_counter_reset_options(
        self, options: list[dict[str, int | str]]
    ) -> str:
        if not options:
            return "⚠️ В текущем цикле нет игроков для сброса счетчика."
        lines = ["🚨 Активный счетчик нарушений", ""]
        lines.extend(
            f"{idx}. {row['player_name']} — {row['violations']}"
            for idx, row in enumerate(options, 1)
        )
        return "\n".join(lines)

    async def violations_ranking_current_cycle(self, period_start, period_end) -> str:
        ranked = await self.violations_ranking_current_cycle_data(period_start, period_end)
        if not ranked:
            return "✅ За текущий цикл нарушений пока нет."
        lines = ["🚨 Нарушения за текущий цикл", ""]
        lines.extend(
            f"{idx}. {row['player_name']} — всего: {row['violations']}, активных: {row['active_violations']}"
            for idx, row in enumerate(ranked, 1)
        )
        return "\n".join(lines)

    async def build_player_violations_report(self, period_start, period_end, player_tag: str, player_name: str) -> str:
        war_rows = await self.war_repo.list_player_violations_in_period(
            clan_tag=self.config.main_clan_tag,
            player_tag=player_tag,
            period_start=period_start,
            period_end=period_end,
        )
        capital_rows = await self.capital_violation_repo.list_for_player_in_period(
            player_tag, period_start, period_end
        )
        entries: list[tuple[datetime, list[str]]] = []
        for violation, attack, war in war_rows:
            war_type = "ЛВК" if war.war_type == WarType.CWL else "КВ"
            if violation.code == ViolationCode.CWL_MISSED_ATTACK and attack is None:
                detail_lines = [
                    f"{violation.detected_at:%Y-%m-%d %H:%M} | ЛВК | пропуск атаки",
                    f"Код: {violation.code.value}",
                    f"Причина: {violation.reason_text}",
                    f"Война: против {war.opponent_name}",
                ]
            else:
                assert attack is not None
                detail_lines = [
                    f"{violation.detected_at:%Y-%m-%d %H:%M} | {war_type} | "
                    f"{attack.attacker_position} -> {attack.defender_position}",
                    f"Код: {violation.code.value}",
                    f"Причина: {violation.reason_text}",
                ]
            entries.append((violation.detected_at, detail_lines))
        for violation, weekend in capital_rows:
            assert weekend.end_time is not None
            entries.append(
                (
                    weekend.end_time,
                    [
                        f"{weekend.end_time:%Y-%m-%d %H:%M} | Столица",
                        f"Код: {violation.code}",
                        f"Причина: {violation.reason_text}",
                        f"Атак в рейде: {violation.attacks}",
                    ],
                )
            )
        entries.sort(key=lambda entry: entry[0])
        active_count = await self.active_violation_counter.count_for_player(
            player_tag, period_start, period_end
        )
        if not entries:
            return (
                f"✅ У игрока {player_name} нет нарушений за текущий цикл.\n"
                f"Активный счетчик нарушений: {active_count}"
            )

        lines = [
            f"🚨 Нарушения игрока: {player_name}",
            f"Всего нарушений за цикл: {len(entries)}",
            f"Активный счетчик нарушений: {active_count}",
            "",
        ]
        for idx, (_, detail_lines) in enumerate(entries, 1):
            lines.append(f"{idx}. {detail_lines[0]}")
            lines.extend(detail_lines[1:])
            if idx < len(entries):
                lines.append("")
        return "\n".join(lines)
