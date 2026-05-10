from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.repositories.donations import DonationSnapshotRepository
from app.repositories.stats import StatsRepository
from app.services.period import PeriodService
from app.utils.time import utcnow


@dataclass(slots=True)
class DonationRankingRow:
    player_name: str
    player_tag: str
    donations: int


class DonationService:
    def __init__(self, session: AsyncSession, config: AppYamlConfig) -> None:
        self.session = session
        self.config = config
        self.repo = DonationSnapshotRepository(session)
        self.stats = StatsRepository(session)

    async def record_snapshot(self, *, player_tag: str, player_id: int | None, clan_tag: str, donations: int, donations_received: int) -> None:
        await self.repo.add_snapshot(
            player_tag=player_tag,
            player_id=player_id,
            clan_tag=clan_tag,
            observed_at=utcnow(),
            donations=donations,
            donations_received=donations_received,
        )

    async def calculate_player_donations_for_period(self, player_tag, start, end) -> int:
        baseline = await self.repo.get_last_snapshot_before(player_tag, start)
        snaps = await self.repo.list_snapshots_in_period(player_tag, start, end)
        points = ([baseline] if baseline else []) + snaps
        if len(points) < 2:
            return 0
        total = 0
        for prev, cur in zip(points, points[1:]):
            delta = cur.donations - prev.donations if cur.donations >= prev.donations else cur.donations
            total += max(delta, 0)
        return total

    async def build_current_cycle_donation_ranking(self) -> list[DonationRankingRow]:
        period = await PeriodService(self.session).current_cycle()
        rows = await self.stats.aggregated_player_stats(clan_tag=self.config.main_clan_tag, period_start=period.start, period_end=period.end)
        ranking = []
        for row in rows:
            donated = await self.calculate_player_donations_for_period(row.player_tag, period.start, period.end)
            ranking.append(DonationRankingRow(row.player_name, row.player_tag, donated))
        return sorted(ranking, key=lambda x: x.donations, reverse=True)

    def format_donation_ranking(self, ranking: list[DonationRankingRow]) -> str:
        lines = ["🧪 Dev-донаты", ""]
        for idx, row in enumerate(ranking, 1):
            lines.append(f"{idx}. {row.player_name} — {row.donations}")
        return "\n".join(lines)
