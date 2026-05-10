from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlayerDonationSnapshot


class DonationSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_snapshot(self, **kwargs) -> PlayerDonationSnapshot:
        snap = PlayerDonationSnapshot(**kwargs)
        self.session.add(snap)
        await self.session.flush()
        return snap

    async def list_snapshots_for_player(self, player_tag: str) -> list[PlayerDonationSnapshot]:
        stmt = select(PlayerDonationSnapshot).where(PlayerDonationSnapshot.player_tag == player_tag).order_by(PlayerDonationSnapshot.observed_at.asc())
        return list((await self.session.execute(stmt)).scalars())

    async def get_last_snapshot_before(self, player_tag: str, dt: datetime) -> PlayerDonationSnapshot | None:
        stmt = (
            select(PlayerDonationSnapshot)
            .where(PlayerDonationSnapshot.player_tag == player_tag, PlayerDonationSnapshot.observed_at < dt)
            .order_by(PlayerDonationSnapshot.observed_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_snapshots_in_period(self, player_tag: str, start: datetime, end: datetime) -> list[PlayerDonationSnapshot]:
        stmt = (
            select(PlayerDonationSnapshot)
            .where(PlayerDonationSnapshot.player_tag == player_tag, PlayerDonationSnapshot.observed_at >= start, PlayerDonationSnapshot.observed_at <= end)
            .order_by(PlayerDonationSnapshot.observed_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars())
