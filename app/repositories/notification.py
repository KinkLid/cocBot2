from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminNotificationHistory


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def was_sent(self, admin_id: int, event_key: str) -> bool:
        result = await self.session.execute(
            select(AdminNotificationHistory).where(
                AdminNotificationHistory.admin_telegram_id == admin_id,
                AdminNotificationHistory.event_key == event_key,
            )
        )
        return result.scalar_one_or_none() is not None

    async def mark_sent(self, admin_id: int, event_key: str, event_type: str, now: datetime) -> None:
        self.session.add(
            AdminNotificationHistory(
                admin_telegram_id=admin_id,
                event_key=event_key,
                event_type=event_type,
                created_at=now,
            )
        )
        await self.session.flush()
