from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CapitalRaidViolation, CapitalRaidWeekend


class CapitalRaidViolationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def delete_for_weekend(self, weekend_id: int) -> None:
        await self.session.execute(
            delete(CapitalRaidViolation).where(CapitalRaidViolation.weekend_id == weekend_id)
        )

    async def add_many(self, violations: list[CapitalRaidViolation]) -> None:
        self.session.add_all(violations)
        await self.session.flush()

    async def count_for_player_in_period(self, player_tag, period_start, period_end) -> int:
        result = await self.session.execute(
            select(func.count(CapitalRaidViolation.id))
            .join(CapitalRaidWeekend, CapitalRaidWeekend.id == CapitalRaidViolation.weekend_id)
            .where(
                CapitalRaidViolation.player_tag == player_tag,
                CapitalRaidWeekend.end_time >= period_start,
                CapitalRaidWeekend.end_time <= period_end,
            )
        )
        return int(result.scalar_one())

    async def list_for_player_in_period(self, player_tag, period_start, period_end):
        result = await self.session.execute(
            select(CapitalRaidViolation, CapitalRaidWeekend)
            .join(CapitalRaidWeekend, CapitalRaidWeekend.id == CapitalRaidViolation.weekend_id)
            .where(
                CapitalRaidViolation.player_tag == player_tag,
                CapitalRaidWeekend.end_time >= period_start,
                CapitalRaidWeekend.end_time <= period_end,
            )
            .order_by(CapitalRaidWeekend.end_time.asc(), CapitalRaidViolation.id.asc())
        )
        return list(result.all())

    async def list_for_player_all_time(
        self,
        *,
        clan_tag: str,
        player_tag: str,
    ) -> list[tuple[CapitalRaidViolation, CapitalRaidWeekend]]:
        result = await self.session.execute(
            select(CapitalRaidViolation, CapitalRaidWeekend)
            .join(
                CapitalRaidWeekend,
                CapitalRaidWeekend.id == CapitalRaidViolation.weekend_id,
            )
            .where(
                CapitalRaidViolation.player_tag == player_tag,
                CapitalRaidWeekend.clan_tag == clan_tag,
            )
            .order_by(
                CapitalRaidWeekend.end_time.asc().nulls_last(),
                CapitalRaidViolation.id.asc(),
            )
        )
        return list(result.all())

    async def aggregated_current_cycle(self, clan_tag, period_start, period_end) -> dict[str, int]:
        result = await self.session.execute(
            select(CapitalRaidViolation.player_tag, func.count(CapitalRaidViolation.id))
            .join(CapitalRaidWeekend, CapitalRaidWeekend.id == CapitalRaidViolation.weekend_id)
            .where(
                CapitalRaidWeekend.clan_tag == clan_tag,
                CapitalRaidWeekend.end_time >= period_start,
                CapitalRaidWeekend.end_time <= period_end,
            )
            .group_by(CapitalRaidViolation.player_tag)
        )
        return {player_tag: int(count) for player_tag, count in result.all()}

    async def list_for_weekend_ids(self, weekend_ids: list[int]) -> list[CapitalRaidViolation]:
        if not weekend_ids:
            return []
        result = await self.session.execute(
            select(CapitalRaidViolation).where(CapitalRaidViolation.weekend_id.in_(weekend_ids))
        )
        return list(result.scalars())
