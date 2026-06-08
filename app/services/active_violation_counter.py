from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CapitalRaidViolation, Violation
from app.repositories.violation_counter_reset import ViolationCounterResetRepository


class ActiveViolationCounterService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.resets = ViolationCounterResetRepository(session)

    async def counts_for_players(
        self,
        player_tags: list[str],
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> dict[str, int]:
        if not player_tags:
            return {}

        latest_resets = await self.resets.latest_resets_for_players(player_tags, cycle_start)
        war_rows = await self.session.execute(
            select(Violation.player_tag, Violation.detected_at).where(
                Violation.player_tag.in_(player_tags),
                Violation.detected_at >= cycle_start,
                Violation.detected_at <= cycle_end,
            )
        )
        capital_rows = await self.session.execute(
            select(CapitalRaidViolation.player_tag, CapitalRaidViolation.detected_at).where(
                CapitalRaidViolation.player_tag.in_(player_tags),
                CapitalRaidViolation.detected_at >= cycle_start,
                CapitalRaidViolation.detected_at <= cycle_end,
            )
        )

        counts = {player_tag: 0 for player_tag in player_tags}
        for player_tag, detected_at in [*war_rows.all(), *capital_rows.all()]:
            reset_at = latest_resets.get(player_tag)
            if reset_at is None or detected_at > reset_at:
                counts[player_tag] += 1
        return counts

    async def count_for_player(
        self,
        player_tag: str,
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> int:
        counts = await self.counts_for_players([player_tag], cycle_start, cycle_end)
        return counts.get(player_tag, 0)
