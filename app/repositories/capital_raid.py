from __future__ import annotations

from sqlalchemy import delete, select
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
