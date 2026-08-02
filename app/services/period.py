from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.period import PeriodRange
from app.models import CycleBoundary
from app.utils.time import utcnow


_ALL_TIME_START = datetime(1970, 1, 1, tzinfo=UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class PeriodService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _boundaries(self) -> list[CycleBoundary]:
        result = await self.session.execute(select(CycleBoundary).order_by(CycleBoundary.boundary_at.asc()))
        return list(result.scalars().all())

    async def current_cycle(self, now: datetime | None = None) -> PeriodRange:
        now = _aware(now or utcnow())
        boundaries = await self._boundaries()
        previous = [b for b in boundaries if _aware(b.boundary_at) <= now]
        if not previous:
            return PeriodRange(start=now, end=now, label="Текущий цикл")
        start = _aware(previous[-1].boundary_at)
        return PeriodRange(start=start, end=now, label="Текущий цикл")

    async def previous_cycle(self, now: datetime | None = None) -> PeriodRange:
        now = _aware(now or utcnow())
        boundaries = await self._boundaries()
        previous = [b for b in boundaries if _aware(b.boundary_at) <= now]
        if len(previous) < 2:
            raise ValueError("Прошлый цикл недоступен: в базе недостаточно границ циклов ЛВК")
        return PeriodRange(
            start=_aware(previous[-2].boundary_at),
            end=_aware(previous[-1].boundary_at),
            label="Прошлый цикл",
        )

    async def completed_cycles(self, now: datetime | None = None) -> list[PeriodRange]:
        now = _aware(now or utcnow())
        boundaries = [_aware(item.boundary_at) for item in await self._boundaries()]
        completed = [boundary for boundary in boundaries if boundary <= now]
        cycles = [
            PeriodRange(
                start=completed[index - 1],
                end=completed[index],
                label=f"Цикл {completed[index - 1]:%d.%m.%Y} — {completed[index]:%d.%m.%Y}",
            )
            for index in range(1, len(completed))
        ]
        cycles.reverse()
        return cycles

    def all_time(self, now: datetime | None = None) -> PeriodRange:
        return PeriodRange(
            start=_ALL_TIME_START,
            end=_aware(now or utcnow()),
            label="За всё время",
        )

    def custom_period(self, start: datetime, end: datetime) -> PeriodRange:
        start = _aware(start)
        end = _aware(end)
        if end < start:
            raise ValueError("Дата конца периода меньше даты начала")
        return PeriodRange(start=start, end=end, label="Произвольный период")
