from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ViolationCounterReset


class ViolationCounterResetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_reset(
        self,
        player_tag: str,
        cycle_start: datetime,
        reset_at: datetime,
        reset_by_admin_telegram_id: int,
        reset_amount: int,
    ) -> ViolationCounterReset:
        reset = ViolationCounterReset(
            player_tag=player_tag,
            cycle_start=cycle_start,
            reset_at=reset_at,
            reset_by_admin_telegram_id=reset_by_admin_telegram_id,
            reset_amount=reset_amount,
        )
        self.session.add(reset)
        await self.session.flush()
        return reset

    async def latest_reset_for_player(
        self, player_tag: str, cycle_start: datetime
    ) -> ViolationCounterReset | None:
        result = await self.session.execute(
            select(ViolationCounterReset)
            .where(
                ViolationCounterReset.player_tag == player_tag,
                ViolationCounterReset.cycle_start == cycle_start,
            )
            .order_by(
                ViolationCounterReset.reset_at.desc(),
                ViolationCounterReset.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_players(
        self,
        player_tags: list[str],
        cycle_start: datetime,
    ) -> list[ViolationCounterReset]:
        if not player_tags:
            return []
        result = await self.session.scalars(
            select(ViolationCounterReset)
            .where(
                ViolationCounterReset.player_tag.in_(player_tags),
                ViolationCounterReset.cycle_start == cycle_start,
            )
            .order_by(ViolationCounterReset.reset_at.asc(), ViolationCounterReset.id.asc())
        )
        return list(result.all())

    async def latest_resets_for_players(
        self, player_tags: list[str], cycle_start: datetime
    ) -> dict[str, datetime]:
        resets = await self.list_for_players(player_tags, cycle_start)
        latest: dict[str, datetime] = {}
        for reset in resets:
            latest[reset.player_tag] = reset.reset_at
        return latest
