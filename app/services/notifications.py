from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import AppYamlConfig
from app.repositories.notification import NotificationRepository

logger = logging.getLogger(__name__)


class AdminNotifier:
    def __init__(
        self,
        session: AsyncSession,
        config: AppYamlConfig,
        sender: Callable[[int, str], Awaitable[None]],
    ) -> None:
        self.session = session
        self.config = config
        self.sender = sender
        self.repo = NotificationRepository(session)

    async def notify_once(self, *, event_key: str, event_type: str, text: str, now: datetime) -> None:
        for admin_id in self.config.admin_telegram_ids:
            if await self.repo.was_sent(admin_id, event_key):
                continue
            await self.sender(admin_id, text)
            await self.repo.mark_sent(admin_id, event_key, event_type, now)
            logger.info("Admin notification sent: %s -> %s", event_type, admin_id)
