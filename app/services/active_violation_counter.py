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
        events: dict[str, list[datetime]] = {player_tag: [] for player_tag in player_tags}
        for player_tag, detected_at in [*war_rows.all(), *capital_rows.all()]:
            events.setdefault(player_tag, []).append(detected_at)

        resets = await self.resets.list_for_players(player_tags, cycle_start)
        resets_by_player = {player_tag: [] for player_tag in player_tags}
        for reset in resets:
            resets_by_player.setdefault(reset.player_tag, []).append(reset)

        counts: dict[str, int] = {}
        for player_tag in player_tags:
            player_resets = resets_by_player.get(player_tag, [])
            legacy_reset = None
            for reset in player_resets:
                if reset.reset_amount is None:
                    legacy_reset = reset
            if legacy_reset is None:
                violations_after_legacy_reset = len(events.get(player_tag, []))
                partial_reset_sum = sum(
                    reset.reset_amount or 0
                    for reset in player_resets
                    if reset.reset_amount is not None
                )
            else:
                violations_after_legacy_reset = sum(
                    1 for detected_at in events.get(player_tag, []) if detected_at > legacy_reset.reset_at
                )
                partial_reset_sum = sum(
                    reset.reset_amount or 0
                    for reset in player_resets
                    if reset.reset_amount is not None and reset.reset_at > legacy_reset.reset_at
                )
            counts[player_tag] = max(0, violations_after_legacy_reset - partial_reset_sum)
        return counts

    async def count_for_player(
        self,
        player_tag: str,
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> int:
        counts = await self.counts_for_players([player_tag], cycle_start, cycle_end)
        return counts.get(player_tag, 0)

    async def reduce_for_player(
        self,
        *,
        player_tag: str,
        cycle_start: datetime,
        cycle_end: datetime,
        amount: int,
        admin_telegram_id: int,
        reset_at: datetime,
    ) -> int:
        if amount not in {1, 2, 3}:
            raise ValueError("Количество списываемых нарушений должно быть 1, 2 или 3")
        current_count = await self.count_for_player(player_tag, cycle_start, cycle_end)
        if current_count < amount:
            raise ValueError(
                f"Нельзя списать {amount}: у игрока только {current_count} активных нарушений"
            )
        await self.resets.add_reset(
            player_tag=player_tag,
            cycle_start=cycle_start,
            reset_at=reset_at,
            reset_by_admin_telegram_id=admin_telegram_id,
            reset_amount=amount,
        )
        await self.session.flush()
        return current_count - amount
