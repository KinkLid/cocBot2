from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.repositories.stats import StatsRepository
from app.schemas.dto import PlayerStatsDTO


@dataclass(slots=True)
class FormattedStats:
    text: str
    rows: list[PlayerStatsDTO]


class StatsService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = StatsRepository(session)

    async def player_stats(self, period_start, period_end, player_tag: str) -> PlayerStatsDTO:
        rows = await self.repo.aggregated_player_stats(
            clan_tag=self.config.main_clan_tag,
            period_start=period_start,
            period_end=period_end,
            player_tags=[player_tag],
        )
        ranked = await self.clan_stats(period_start, period_end)
        ranking_map = {row.player_tag: row.place for row in ranked.rows}
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
            violations=row.violations,
            place=ranking_map.get(row.player_tag, 0),
            clan_rank=row.clan_rank,
        )

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
                violations=row.violations,
                place=places[row.player_tag],
                clan_rank=row.clan_rank,
            )
            for row in sorted_rows
        ]
        text = "\n\n".join(self.format_player_card(row, period_start.date().isoformat(), period_end.date().isoformat()) for row in dto_rows)
        return FormattedStats(text=text, rows=dto_rows)

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
        if row.violations > 0:
            parts.append(f"⚠️ Нарушений: {row.violations}")
        parts.append(f"🏅 Место в клане: {row.place}")
        return "\n".join(parts)
