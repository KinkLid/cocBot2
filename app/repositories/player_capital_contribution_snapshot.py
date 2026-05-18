from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlayerCapitalContributionSnapshot


class PlayerCapitalContributionSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, player_tag: str, clan_tag: str, observed_at: datetime, value: int) -> None:
        self.session.add(PlayerCapitalContributionSnapshot(
            player_tag=player_tag,
            clan_tag=clan_tag,
            observed_at=observed_at,
            value=value,
        ))

    async def get_first_at_or_after(self, player_tag: str, clan_tag: str, observed_at: datetime) -> PlayerCapitalContributionSnapshot | None:
        res = await self.session.execute(
            select(PlayerCapitalContributionSnapshot)
            .where(
                PlayerCapitalContributionSnapshot.player_tag == player_tag,
                PlayerCapitalContributionSnapshot.clan_tag == clan_tag,
                PlayerCapitalContributionSnapshot.observed_at >= observed_at,
            )
            .order_by(PlayerCapitalContributionSnapshot.observed_at.asc(), PlayerCapitalContributionSnapshot.id.asc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def get_latest(self, player_tag: str, clan_tag: str) -> PlayerCapitalContributionSnapshot | None:
        res = await self.session.execute(
            select(PlayerCapitalContributionSnapshot)
            .where(
                PlayerCapitalContributionSnapshot.player_tag == player_tag,
                PlayerCapitalContributionSnapshot.clan_tag == clan_tag,
            )
            .order_by(PlayerCapitalContributionSnapshot.observed_at.desc(), PlayerCapitalContributionSnapshot.id.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()
