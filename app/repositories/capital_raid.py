from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CapitalRaidParticipant, CapitalRaidWeekend


class CapitalRaidRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_weekend(self, clan_tag: str, raid_season_id: str) -> CapitalRaidWeekend | None:
        res = await self.session.execute(select(CapitalRaidWeekend).where(CapitalRaidWeekend.clan_tag == clan_tag, CapitalRaidWeekend.raid_season_id == raid_season_id))
        return res.scalar_one_or_none()

    async def upsert_weekend(self, weekend: CapitalRaidWeekend) -> CapitalRaidWeekend:
        existing = await self.get_weekend(weekend.clan_tag, weekend.raid_season_id)
        if existing is None:
            self.session.add(weekend)
            await self.session.flush()
            return weekend
        existing.state = weekend.state
        existing.start_time = weekend.start_time
        existing.end_time = weekend.end_time
        existing.total_loot = weekend.total_loot
        existing.total_attacks = weekend.total_attacks
        existing.enemy_districts_destroyed = weekend.enemy_districts_destroyed
        existing.offensive_reward = weekend.offensive_reward
        existing.defensive_reward = weekend.defensive_reward
        existing.processed_at = weekend.processed_at
        await self.session.flush()
        return existing

    async def replace_participants(self, weekend_id: int, participants: list[CapitalRaidParticipant]) -> None:
        await self.session.execute(delete(CapitalRaidParticipant).where(CapitalRaidParticipant.weekend_id == weekend_id))
        for p in participants:
            self.session.add(p)
        await self.session.flush()

    async def get_latest_completed_weekend(self, clan_tag: str) -> CapitalRaidWeekend | None:
        res = await self.session.execute(
            select(CapitalRaidWeekend)
            .where(CapitalRaidWeekend.clan_tag == clan_tag, CapitalRaidWeekend.end_time.is_not(None))
            .order_by(CapitalRaidWeekend.end_time.desc(), CapitalRaidWeekend.id.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def list_participants_for_weekend(self, weekend_id: int) -> list[CapitalRaidParticipant]:
        res = await self.session.execute(
            select(CapitalRaidParticipant).where(CapitalRaidParticipant.weekend_id == weekend_id)
        )
        return list(res.scalars())

    async def count_participants_for_weekend(self, weekend_id: int) -> int:
        res = await self.session.execute(
            select(func.count(CapitalRaidParticipant.id)).where(CapitalRaidParticipant.weekend_id == weekend_id)
        )
        return int(res.scalar_one())

    async def list_latest_completed_weekends(self, clan_tag: str, limit: int) -> list[CapitalRaidWeekend]:
        res = await self.session.execute(
            select(CapitalRaidWeekend)
            .where(CapitalRaidWeekend.clan_tag == clan_tag, CapitalRaidWeekend.end_time.is_not(None))
            .order_by(CapitalRaidWeekend.end_time.desc(), CapitalRaidWeekend.id.desc())
            .limit(limit)
        )
        return list(res.scalars())

    async def list_participants_for_weekend_ids(self, weekend_ids: list[int]) -> list[CapitalRaidParticipant]:
        if not weekend_ids:
            return []
        res = await self.session.execute(
            select(CapitalRaidParticipant).where(CapitalRaidParticipant.weekend_id.in_(weekend_ids))
        )
        return list(res.scalars())

    async def count_completed_weekends(self, clan_tag: str) -> int:
        res = await self.session.execute(
            select(func.count(CapitalRaidWeekend.id)).where(
                CapitalRaidWeekend.clan_tag == clan_tag,
                CapitalRaidWeekend.end_time.is_not(None),
            )
        )
        return int(res.scalar_one())

    async def list_weekends_for_period(self, clan_tag: str, period_start, period_end) -> list[CapitalRaidWeekend]:
        res = await self.session.execute(
            select(CapitalRaidWeekend)
            .where(
                CapitalRaidWeekend.clan_tag == clan_tag,
                CapitalRaidWeekend.end_time.is_not(None),
                CapitalRaidWeekend.end_time >= period_start,
                CapitalRaidWeekend.end_time <= period_end,
            )
            .order_by(CapitalRaidWeekend.end_time.asc())
        )
        return list(res.scalars())

    async def list_participants_for_period(self, clan_tag: str, period_start, period_end) -> list[CapitalRaidParticipant]:
        res = await self.session.execute(
            select(CapitalRaidParticipant)
            .join(CapitalRaidWeekend, CapitalRaidWeekend.id == CapitalRaidParticipant.weekend_id)
            .where(
                CapitalRaidWeekend.clan_tag == clan_tag,
                CapitalRaidWeekend.end_time.is_not(None),
                CapitalRaidWeekend.end_time >= period_start,
                CapitalRaidWeekend.end_time <= period_end,
            )
        )
        return list(res.scalars())
