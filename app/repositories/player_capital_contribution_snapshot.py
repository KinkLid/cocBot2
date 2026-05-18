from __future__ import annotations

from datetime import datetime

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
