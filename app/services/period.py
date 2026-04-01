from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.period import PeriodRange
from app.models import CycleBoundary
from app.utils.time import utcnow


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class PeriodService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _boundaries(self) -> list[CycleBoundary]:
        result = await self.session.execute(select(CycleBoundary).order_by(CycleBoundary.boundary_at.asc()))
        return list(result.scalars().all())

    async def current_cycle(self, now: datetime | None = None) -> PeriodRange:
        now = now or utcnow()
        boundaries = await self._boundaries()
        now = _aware(now)
        previous = [b for b in boundaries if _aware(b.boundary_at) <= now]
        if not previous:
            return PeriodRange(start=now, end=now, label="Текущий цикл")
        start = _aware(previous[-1].boundary_at)
        return PeriodRange(start=start, end=now, label="Текущий цикл")

    async def previous_cycle(self, now: datetime | None = None) -> PeriodRange:
        now = now or utcnow()
        boundaries = await self._boundaries()
        now = _aware(now)
        previous = [b for b in boundaries if _aware(b.boundary_at) <= now]
        if len(previous) < 2:
            raise ValueError("Недостаточно данных по ЛВК для прошлого цикла")
        return PeriodRange(start=_aware(previous[-2].boundary_at), end=_aware(previous[-1].boundary_at), label="Прошлый цикл")

    def custom_period(self, start: datetime, end: datetime) -> PeriodRange:
        if end < start:
            raise ValueError("Дата конца периода меньше даты начала")
        return PeriodRange(start=start, end=end, label="Произвольный период")
