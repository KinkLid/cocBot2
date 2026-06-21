from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ManualContributionAdjustment, PlayerAccount


@dataclass(slots=True)
class ManualContributionPlayerOption:
    player_id: int
    player_tag: str
    player_name: str
    clan_rank: int | None


class ManualContributionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def current_main_clan_players(self, clan_tag: str) -> list[ManualContributionPlayerOption]:
        rows = await self.session.execute(
            select(PlayerAccount.id, PlayerAccount.player_tag, PlayerAccount.name, PlayerAccount.current_clan_rank)
            .where(PlayerAccount.current_in_clan.is_(True), PlayerAccount.current_clan_tag == clan_tag)
            .order_by(PlayerAccount.current_clan_rank.asc().nulls_last(), PlayerAccount.name.asc())
        )
        return [ManualContributionPlayerOption(*row) for row in rows.all()]

    async def get_current_main_clan_player(self, player_id: int, clan_tag: str) -> PlayerAccount | None:
        return await self.session.scalar(
            select(PlayerAccount).where(
                PlayerAccount.id == player_id,
                PlayerAccount.current_in_clan.is_(True),
                PlayerAccount.current_clan_tag == clan_tag,
            )
        )

    async def add_manual_adjustment(
        self,
        player_id: int,
        clan_tag: str,
        points: int,
        comment: str,
        created_by_telegram_id: int,
        created_by_username: str | None,
        created_at: datetime,
    ) -> ManualContributionAdjustment:
        if points <= 0:
            raise ValueError("points must be positive")
        if not (3 <= len(comment.strip()) <= 500):
            raise ValueError("comment must contain 3 to 500 characters")
        adjustment = ManualContributionAdjustment(
            player_id=player_id,
            clan_tag=clan_tag,
            points=points,
            comment=comment.strip(),
            created_by_telegram_id=created_by_telegram_id,
            created_by_username=created_by_username,
            created_at=created_at,
        )
        self.session.add(adjustment)
        await self.session.flush()
        return adjustment

    async def manual_adjustments_for_player(self, player_id: int, clan_tag: str, period_start: datetime, period_end: datetime) -> list[ManualContributionAdjustment]:
        if not hasattr(self.session, "scalars"):
            return []
        rows = await self.session.scalars(
            select(ManualContributionAdjustment)
            .where(
                ManualContributionAdjustment.player_id == player_id,
                ManualContributionAdjustment.clan_tag == clan_tag,
                ManualContributionAdjustment.created_at >= period_start,
                ManualContributionAdjustment.created_at < period_end,
            )
            .order_by(ManualContributionAdjustment.created_at.asc(), ManualContributionAdjustment.id.asc())
        )
        return list(rows.all())

    async def manual_adjustment_totals(self, player_ids: list[int], clan_tag: str, period_start: datetime, period_end: datetime) -> dict[int, int]:
        if not player_ids:
            return {}
        if not hasattr(self.session, "execute"):
            return {}
        rows = await self.session.execute(
            select(ManualContributionAdjustment.player_id, func.coalesce(func.sum(ManualContributionAdjustment.points), 0))
            .where(
                ManualContributionAdjustment.player_id.in_(player_ids),
                ManualContributionAdjustment.clan_tag == clan_tag,
                ManualContributionAdjustment.created_at >= period_start,
                ManualContributionAdjustment.created_at < period_end,
            )
            .group_by(ManualContributionAdjustment.player_id)
        )
        return {int(pid): int(total) for pid, total in rows.all()}
